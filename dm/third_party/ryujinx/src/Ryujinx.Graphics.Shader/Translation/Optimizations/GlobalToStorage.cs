using Ryujinx.Graphics.Shader.IntermediateRepresentation;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using static Ryujinx.Graphics.Shader.IntermediateRepresentation.OperandHelper;

namespace Ryujinx.Graphics.Shader.Translation.Optimizations
{
    static class GlobalToStorage
    {
        private const int DriverReservedCb = 0;

        enum LsMemoryType
        {
            Local,
            Shared,
        }

        private class GtsContext
        {
            private readonly struct Entry
            {
                public readonly int FunctionId;
                public readonly Instruction Inst;
                public readonly StorageKind StorageKind;
                public readonly bool IsMultiTarget;
                public readonly IReadOnlyList<uint> TargetCbs;
                // nxnative: a multi-target function whose misses go through the memory pool table (TryGenerateMultiTargetStorageOp, a loaded pointer among the phi's sources)
                public readonly bool RawFallback;

                public Entry(
                    int functionId,
                    Instruction inst,
                    StorageKind storageKind,
                    bool isMultiTarget,
                    IReadOnlyList<uint> targetCbs,
                    bool rawFallback)
                {
                    FunctionId = functionId;
                    Inst = inst;
                    StorageKind = storageKind;
                    IsMultiTarget = isMultiTarget;
                    TargetCbs = targetCbs;
                    RawFallback = rawFallback;
                }
            }

            private readonly struct LsKey : IEquatable<LsKey>
            {
                public readonly Operand BaseOffset;
                public readonly int ConstOffset;
                public readonly LsMemoryType Type;

                public LsKey(Operand baseOffset, int constOffset, LsMemoryType type)
                {
                    BaseOffset = baseOffset;
                    ConstOffset = constOffset;
                    Type = type;
                }

                public override int GetHashCode()
                {
                    return HashCode.Combine(BaseOffset, ConstOffset, Type);
                }

                public override bool Equals(object obj)
                {
                    return obj is LsKey other && Equals(other);
                }

                public bool Equals(LsKey other)
                {
                    return other.BaseOffset == BaseOffset && other.ConstOffset == ConstOffset && other.Type == Type;
                }
            }

            private readonly List<Entry> _entries;
            private readonly Dictionary<LsKey, Dictionary<uint, SearchResult>> _sharedEntries;
            private readonly HelperFunctionManager _hfm;

            public GtsContext(HelperFunctionManager hfm)
            {
                _entries = [];
                _sharedEntries = new Dictionary<LsKey, Dictionary<uint, SearchResult>>();
                _hfm = hfm;
            }

            public int AddFunction(Operation baseOp, bool isMultiTarget, IReadOnlyList<uint> targetCbs, Function function, bool rawFallback = false)
            {
                int functionId = _hfm.AddFunction(function);

                _entries.Add(new Entry(functionId, baseOp.Inst, baseOp.StorageKind, isMultiTarget, targetCbs, rawFallback));

                return functionId;
            }

            public bool TryGetFunctionId(Operation baseOp, bool isMultiTarget, List<uint> targetCbs, out int functionId, bool rawFallback = false)
            {
                foreach (Entry entry in _entries)
                {
                    if (entry.Inst != baseOp.Inst ||
                        entry.StorageKind != baseOp.StorageKind ||
                        entry.IsMultiTarget != isMultiTarget ||
                        entry.RawFallback != rawFallback ||
                        entry.TargetCbs.Count != targetCbs.Count)
                    {
                        continue;
                    }

                    bool allEqual = true;

                    for (int index = 0; index < targetCbs.Count; index++)
                    {
                        if (targetCbs[index] != entry.TargetCbs[index])
                        {
                            allEqual = false;
                            break;
                        }
                    }

                    if (allEqual)
                    {
                        functionId = entry.FunctionId;
                        return true;
                    }
                }

                functionId = -1;
                return false;
            }

            public void AddMemoryTargetCb(LsMemoryType type, Operand baseOffset, int constOffset, uint targetCb, SearchResult result)
            {
                LsKey key = new(baseOffset, constOffset, type);

                if (!_sharedEntries.TryGetValue(key, out Dictionary<uint, SearchResult> targetCbs))
                {
                    // No entry with this base offset, create a new one.

                    targetCbs = new Dictionary<uint, SearchResult>() { { targetCb, result } };

                    _sharedEntries.Add(key, targetCbs);
                }
                else if (targetCbs.TryGetValue(targetCb, out SearchResult existingResult))
                {
                    // If our entry already exists, but does not match the new result,
                    // we set the offset to null to indicate there are multiple possible offsets.
                    // This will be used on the multi-target access that does not need to know the offset.

                    if (existingResult.Offset != null &&
                        (existingResult.Offset != result.Offset ||
                        existingResult.ConstOffset != result.ConstOffset))
                    {
                        targetCbs[targetCb] = new SearchResult(result.SbCbSlot, result.SbCbOffset);
                    }
                }
                else
                {
                    // An entry for this base offset already exists, but not for the specified
                    // constant buffer region where the storage buffer base address and size
                    // comes from.

                    targetCbs.Add(targetCb, result);
                }
            }

            public bool TryGetMemoryTargetCb(LsMemoryType type, Operand baseOffset, int constOffset, out SearchResult result)
            {
                LsKey key = new(baseOffset, constOffset, type);

                if (_sharedEntries.TryGetValue(key, out Dictionary<uint, SearchResult> targetCbs) && targetCbs.Count == 1)
                {
                    SearchResult candidateResult = targetCbs.Values.First();

                    if (candidateResult.Found)
                    {
                        result = candidateResult;

                        return true;
                    }
                }

                result = default;

                return false;
            }
        }

        private readonly struct SearchResult
        {
            public static SearchResult NotFound => new(-1, 0);
            public bool Found => SbCbSlot != -1;
            public int SbCbSlot { get; }
            public int SbCbOffset { get; }
            public Operand Offset { get; }
            public int ConstOffset { get; }

            public SearchResult(int sbCbSlot, int sbCbOffset)
            {
                SbCbSlot = sbCbSlot;
                SbCbOffset = sbCbOffset;
            }

            public SearchResult(int sbCbSlot, int sbCbOffset, Operand offset, int constOffset = 0)
            {
                SbCbSlot = sbCbSlot;
                SbCbOffset = sbCbOffset;
                Offset = offset;
                ConstOffset = constOffset;
            }
        }

        public static void RunPass(
            HelperFunctionManager hfm,
            BasicBlock[] blocks,
            ResourceManager resourceManager,
            IGpuAccessor gpuAccessor,
            TargetLanguage targetLanguage)
        {
            GtsContext gtsContext = new(hfm);

            foreach (BasicBlock block in blocks)
            {
                for (LinkedListNode<INode> node = block.Operations.First; node != null; node = node.Next)
                {
                    if (node.Value is not Operation operation)
                    {
                        continue;
                    }

                    if (IsGlobalMemory(operation.StorageKind))
                    {
                        LinkedListNode<INode> nextNode = ReplaceGlobalMemoryWithStorage(
                            gtsContext,
                            resourceManager,
                            gpuAccessor,
                            targetLanguage,
                            block,
                            node);

                        if (nextNode == null)
                        {
                            // The returned value being null means that the global memory replacement failed,
                            // so we just make loads read 0 and stores do nothing.
                            // nxnative: a compare-and-swap returns its comparator (source 2 of the global CAS: address low, high, comparator, value), as
                            // MissedAccessResult does on the helpers' misses (Lichii a6e5217, #140), so the guest's 'while (CAS != cmp)' loop ends

                            gpuAccessor.Log($"Failed to reserve storage buffer for global memory operation \"{operation.Inst}\".");

                            if (operation.Dest != null)
                            {
                                operation.TurnIntoCopy(operation.Inst == Instruction.AtomicCompareAndSwap ? operation.GetSource(2) : Const(0));
                            }
                            else
                            {
                                Utils.DeleteNode(node, operation);
                            }
                        }
                        else
                        {
                            node = nextNode;
                        }
                    }
                    else if (operation.Inst == Instruction.Store &&
                        (operation.StorageKind == StorageKind.SharedMemory ||
                        operation.StorageKind == StorageKind.LocalMemory))
                    {
                        // The NVIDIA compiler can sometimes use shared or local memory as temporary
                        // storage to place the base address and size on, so we need
                        // to be able to find such information stored in memory too.

                        if (TryGetMemoryOffsets(operation, out LsMemoryType type, out Operand baseOffset, out int constOffset))
                        {
                            Operand value = operation.GetSource(operation.SourcesCount - 1);

                            SearchResult result = FindUniqueBaseAddressCb(gtsContext, block, value, needsOffset: false);
                            if (result.Found)
                            {
                                uint targetCb = PackCbSlotAndOffset(result.SbCbSlot, result.SbCbOffset);
                                gtsContext.AddMemoryTargetCb(type, baseOffset, constOffset, targetCb, result);
                            }
                        }
                    }
                }
            }
        }

        private static bool IsGlobalMemory(StorageKind storageKind)
        {
            return storageKind is StorageKind.GlobalMemory or
                   StorageKind.GlobalMemoryS8 or
                   StorageKind.GlobalMemoryS16 or
                   StorageKind.GlobalMemoryU8 or
                   StorageKind.GlobalMemoryU16;
        }

        private static bool IsSmallInt(StorageKind storageKind)
        {
            return storageKind is StorageKind.GlobalMemoryS8 or
                   StorageKind.GlobalMemoryS16 or
                   StorageKind.GlobalMemoryU8 or
                   StorageKind.GlobalMemoryU16;
        }

        private static LinkedListNode<INode> ReplaceGlobalMemoryWithStorage(
            GtsContext gtsContext,
            ResourceManager resourceManager,
            IGpuAccessor gpuAccessor,
            TargetLanguage targetLanguage,
            BasicBlock block,
            LinkedListNode<INode> node)
        {
            Operation operation = node.Value as Operation;
            Operand globalAddress = operation.GetSource(0);
            SearchResult result = FindUniqueBaseAddressCb(gtsContext, block, globalAddress, needsOffset: true);

            if (result.Found)
            {
                // We found the storage buffer that is being accessed.
                // There are two possible paths here, if the operation is simple enough,
                // we just generate the storage access code inline.
                // Otherwise, we generate a function call (and the function if necessary).

                Operand offset = result.Offset;

                bool storageUnaligned = gpuAccessor.QueryHasUnalignedStorageBuffer();

                if (storageUnaligned)
                {
                    Operand baseAddress = Cbuf(result.SbCbSlot, result.SbCbOffset);

                    Operand baseAddressMasked = Local();
                    Operand hostOffset = Local();

                    int alignment = gpuAccessor.QueryHostStorageBufferOffsetAlignment();

                    Operation maskOp = new(Instruction.BitwiseAnd, baseAddressMasked, baseAddress, Const(-alignment));
                    Operation subOp = new(Instruction.Subtract, hostOffset, globalAddress, baseAddressMasked);

                    node.List.AddBefore(node, maskOp);
                    node.List.AddBefore(node, subOp);

                    offset = hostOffset;
                }
                else if (offset == null)
                {
                    Operand baseAddress = Cbuf(result.SbCbSlot, result.SbCbOffset);
                    Operand byteOffset = Local();

                    Operation subOp = new(Instruction.Subtract, byteOffset, globalAddress, baseAddress);

                    node.List.AddBefore(node, subOp);

                    offset = byteOffset;
                }
                else if (result.ConstOffset != 0)
                {
                    Operand newOffset = Local();

                    Operation addOp = new(Instruction.Add, newOffset, offset, Const(result.ConstOffset));

                    node.List.AddBefore(node, addOp);

                    offset = newOffset;
                }

                if (CanUseInlineStorageOp(operation, targetLanguage))
                {
                    return GenerateInlineStorageOp(resourceManager, node, operation, offset, result);
                }
                else
                {
                    if (!TryGenerateSingleTargetStorageOp(
                        gtsContext,
                        resourceManager,
                        targetLanguage,
                        operation,
                        result,
                        out int functionId))
                    {
                        return null;
                    }

                    return GenerateCallStorageOp(node, operation, offset, functionId);
                }
            }
            else
            {
                // Failed to find the storage buffer directly.
                // Try to walk through Phi chains and find all possible constant buffers where
                // the base address might be stored.
                // Generate a helper function that will check all possible storage buffers and use the right one.

                if (!TryGenerateMultiTargetStorageOp(
                    gtsContext,
                    resourceManager,
                    gpuAccessor,
                    targetLanguage,
                    block,
                    operation,
                    out int functionId))
                {
                    return null;
                }

                return GenerateCallStorageOp(node, operation, null, functionId);
            }
        }

        private static bool CanUseInlineStorageOp(Operation operation, TargetLanguage targetLanguage)
        {
            // nxnative: a float atomic is a loop, which needs a helper function (the main function is in SSA form here)
            if (operation.StorageKind != StorageKind.GlobalMemory || operation.Inst.IsAtomicFloat())
            {
                return false;
            }

            return (operation.Inst != Instruction.AtomicMaxS32 &&
                    operation.Inst != Instruction.AtomicMinS32) || targetLanguage == TargetLanguage.Spirv;
        }

        private static LinkedListNode<INode> GenerateInlineStorageOp(
            ResourceManager resourceManager,
            LinkedListNode<INode> node,
            Operation operation,
            Operand offset,
            SearchResult result)
        {
            bool isStore = operation.Inst == Instruction.Store || operation.Inst.IsAtomic();
            if (!resourceManager.TryGetStorageBufferBinding(result.SbCbSlot, result.SbCbOffset, isStore, out int binding))
            {
                return null;
            }

            Operand wordOffset = Local();

            Operand[] sources;

            if (operation.Inst == Instruction.AtomicCompareAndSwap)
            {
                sources =
                [
                    Const(binding),
                    Const(0),
                    wordOffset,
                    operation.GetSource(operation.SourcesCount - 2),
                    operation.GetSource(operation.SourcesCount - 1)
                ];
            }
            else if (isStore)
            {
                sources = [Const(binding), Const(0), wordOffset, operation.GetSource(operation.SourcesCount - 1)];
            }
            else
            {
                sources = [Const(binding), Const(0), wordOffset];
            }

            Operation shiftOp = new(Instruction.ShiftRightU32, wordOffset, offset, Const(2));
            Operation storageOp = new(operation.Inst, StorageKind.StorageBuffer, operation.Dest, sources);

            node.List.AddBefore(node, shiftOp);
            LinkedListNode<INode> newNode = node.List.AddBefore(node, storageOp);

            Utils.DeleteNode(node, operation);

            return newNode;
        }

        private static LinkedListNode<INode> GenerateCallStorageOp(LinkedListNode<INode> node, Operation operation, Operand offset, int functionId)
        {
            // Generate call to a helper function that will perform the storage buffer operation.

            Operand[] sources = new Operand[operation.SourcesCount - 1 + (offset == null ? 2 : 1)];

            sources[0] = Const(functionId);

            if (offset != null)
            {
                // If the offset was supplised, we use that and skip the global address.

                sources[1] = offset;

                for (int srcIndex = 2; srcIndex < operation.SourcesCount; srcIndex++)
                {
                    sources[srcIndex] = operation.GetSource(srcIndex);
                }
            }
            else
            {
                // Use the 64-bit global address which is split in 2 32-bit arguments.

                for (int srcIndex = 0; srcIndex < operation.SourcesCount; srcIndex++)
                {
                    sources[srcIndex + 1] = operation.GetSource(srcIndex);
                }
            }

            bool returnsValue = operation.Dest != null;
            Operand returnValue = returnsValue ? Local() : null;

            Operation callOp = new(Instruction.Call, returnValue, sources);

            LinkedListNode<INode> newNode = node.List.AddBefore(node, callOp);

            if (returnsValue)
            {
                operation.TurnIntoCopy(returnValue);

                return node;
            }
            else
            {
                Utils.DeleteNode(node, operation);

                return newNode;
            }
        }

        private static bool TryGenerateSingleTargetStorageOp(
            GtsContext gtsContext,
            ResourceManager resourceManager,
            TargetLanguage targetLanguage,
            Operation operation,
            SearchResult result,
            out int functionId)
        {
            List<uint> targetCbs = [PackCbSlotAndOffset(result.SbCbSlot, result.SbCbOffset)];

            if (gtsContext.TryGetFunctionId(operation, isMultiTarget: false, targetCbs, out functionId))
            {
                return true;
            }

            int inArgumentsCount = 1;

            if (operation.Inst == Instruction.AtomicCompareAndSwap)
            {
                inArgumentsCount = 3;
            }
            else if (operation.Inst == Instruction.Store || operation.Inst.IsAtomic())
            {
                inArgumentsCount = 2;
            }

            EmitterContext context = new();

            Operand offset = Argument(0);
            Operand compare = null;
            Operand value = null;

            if (inArgumentsCount == 3)
            {
                compare = Argument(1);
                value = Argument(2);
            }
            else if (inArgumentsCount == 2)
            {
                value = Argument(1);
            }

            if (!TryGenerateStorageOp(
                resourceManager,
                targetLanguage,
                context,
                operation.Inst,
                operation.StorageKind,
                offset,
                compare,
                value,
                result,
                out Operand resultValue))
            {
                functionId = 0;
                return false;
            }

            bool returnsValue = resultValue != null;

            if (returnsValue)
            {
                context.Return(resultValue);
            }
            else
            {
                context.Return();
            }

            string functionName = GetFunctionName(operation, isMultiTarget: false, targetCbs);

            Function function = new(
                ControlFlowGraph.Create(context.GetOperations()).Blocks,
                functionName,
                returnsValue,
                inArgumentsCount,
                0);

            functionId = gtsContext.AddFunction(operation, isMultiTarget: false, targetCbs, function);

            return true;
        }

        private static bool TryGenerateMultiTargetStorageOp(
            GtsContext gtsContext,
            ResourceManager resourceManager,
            IGpuAccessor gpuAccessor,
            TargetLanguage targetLanguage,
            BasicBlock block,
            Operation operation,
            out int functionId)
        {
            Queue<PhiNode> phis = new();
            HashSet<PhiNode> visited = [];
            List<uint> targetCbs = [];

            // nxnative: a phi source that traces to no constant buffer and leads to no other phi: an address the shader computed or loaded from memory (the pointer of
            // 'p = cond ? c0[12] : *c0[12]'). Ryujinx drops that path: the helper's range checks against the constant buffers' storage buffers fail and it returns 0.
            // With it, the helper's misses go through the memory pool table (GenerateRawAccess), as an access traced to no storage buffer at all does
            bool loadedPointer = false;

            Operand globalAddress = operation.GetSource(0);

            if (globalAddress.AsgOp is Operation addOp && addOp.Inst == Instruction.Add)
            {
                Operand src1 = addOp.GetSource(0);
                Operand src2 = addOp.GetSource(1);

                if (src1.Type == OperandType.Constant && src2.Type == OperandType.LocalVariable)
                {
                    globalAddress = src2;
                }
                else if (src1.Type == OperandType.LocalVariable && src2.Type == OperandType.Constant)
                {
                    globalAddress = src1;
                }
            }

            if (globalAddress.AsgOp is PhiNode phi && visited.Add(phi))
            {
                phis.Enqueue(phi);
            }
            else
            {
                SearchResult result = FindUniqueBaseAddressCb(gtsContext, block, operation.GetSource(0), needsOffset: false);

                if (result.Found)
                {
                    targetCbs.Add(PackCbSlotAndOffset(result.SbCbSlot, result.SbCbOffset));
                }
                else
                {
                    EnqueueAddPhis(operation.GetSource(0), phis, visited, 8);
                }
            }

            while (phis.TryDequeue(out phi))
            {
                for (int srcIndex = 0; srcIndex < phi.SourcesCount; srcIndex++)
                {
                    BasicBlock phiBlock = phi.GetBlock(srcIndex);
                    Operand phiSource = phi.GetSource(srcIndex);

                    SearchResult result = FindUniqueBaseAddressCb(gtsContext, phiBlock, phiSource, needsOffset: false);

                    if (result.Found)
                    {
                        uint targetCb = PackCbSlotAndOffset(result.SbCbSlot, result.SbCbOffset);

                        if (!targetCbs.Contains(targetCb))
                        {
                            targetCbs.Add(targetCb);
                        }
                    }
                    else if (!EnqueueAddPhis(phiSource, phis, visited, 8) && phiSource.Type == OperandType.LocalVariable && phiSource.AsgOp != null)
                    {
                        loadedPointer = true;
                    }
                }
            }

            targetCbs.Sort();

            bool rawFallback = false;

            if (targetCbs.Count == 0)
            {
                gpuAccessor.Log($"Global memory operation \"{operation.Inst}\" traced to no storage buffer: it goes through the memory pool table.");
            }
            else if (loadedPointer)
            {
                // (the first note keeps 'operation "<inst>" traced to no storage buffer': the Vulkan build and dmsh_build.py mark the pool table read-write from it when a
                // store or an atomic goes there)
                rawFallback = CanUseRawStorageOp(operation);

                gpuAccessor.Log(rawFallback
                    ? $"Global memory operation \"{operation.Inst}\" traced to no storage buffer on one path (a loaded pointer) and to {targetCbs.Count} on the others: an address in none of those goes through the memory pool table."
                    : $"Global memory operation \"{operation.Inst}\" on a small integer has a loaded pointer among its paths: not implemented, an address in none of its {targetCbs.Count} storage buffers is dropped.");
            }

            if (gtsContext.TryGetFunctionId(operation, isMultiTarget: true, targetCbs, out functionId, rawFallback))
            {
                return true;
            }

            if (targetCbs.Count == 0)
            {
                return TryGenerateRawStorageOp(gtsContext, resourceManager, gpuAccessor, operation, out functionId);
            }

            int inArgumentsCount = 2;

            if (operation.Inst == Instruction.AtomicCompareAndSwap)
            {
                inArgumentsCount = 4;
            }
            else if (operation.Inst == Instruction.Store || operation.Inst.IsAtomic())
            {
                inArgumentsCount = 3;
            }

            EmitterContext context = new();

            Operand globalAddressLow = Argument(0);
            Operand globalAddressHigh = Argument(1);

            foreach (uint targetCb in targetCbs)
            {
                (int sbCbSlot, int sbCbOffset) = UnpackCbSlotAndOffset(targetCb);

                Operand baseAddrLow = Cbuf(sbCbSlot, sbCbOffset);
                Operand baseAddrHigh = Cbuf(sbCbSlot, sbCbOffset + 1);
                Operand size = Cbuf(sbCbSlot, sbCbOffset + 2);

                Operand offset = context.ISubtract(globalAddressLow, baseAddrLow);
                Operand borrow = context.ICompareLessUnsigned(globalAddressLow, baseAddrLow);

                Operand inRangeLow = context.ICompareLessUnsigned(offset, size);

                Operand addrHighBorrowed = context.IAdd(globalAddressHigh, borrow);

                Operand inRangeHigh = context.ICompareEqual(addrHighBorrowed, baseAddrHigh);

                Operand inRange = context.BitwiseAnd(inRangeLow, inRangeHigh);

                Operand lblSkip = Label();
                context.BranchIfFalse(lblSkip, inRange);

                Operand compare = null;
                Operand value = null;

                if (inArgumentsCount == 4)
                {
                    compare = Argument(2);
                    value = Argument(3);
                }
                else if (inArgumentsCount == 3)
                {
                    value = Argument(2);
                }

                SearchResult result = new(sbCbSlot, sbCbOffset);

                int alignment = gpuAccessor.QueryHostStorageBufferOffsetAlignment();

                Operand baseAddressMasked = context.BitwiseAnd(baseAddrLow, Const(-alignment));
                Operand hostOffset = context.ISubtract(globalAddressLow, baseAddressMasked);

                if (!TryGenerateStorageOp(
                    resourceManager,
                    targetLanguage,
                    context,
                    operation.Inst,
                    operation.StorageKind,
                    hostOffset,
                    compare,
                    value,
                    result,
                    out Operand resultValue))
                {
                    functionId = 0;
                    return false;
                }

                if (resultValue != null)
                {
                    context.Return(resultValue);
                }
                else
                {
                    context.Return();
                }

                context.MarkLabel(lblSkip);
            }

            // nxnative: the pool table and the write log take their storage buffer slots after the targets' (TryGenerateStorageOp above), so they never push a target out.
            // With no slot left for them the helper is built without the raw path: the loaded path misses as before this fallback existed, and the constant buffer paths
            // keep working (a failure here used to drop the whole access, every path read 0)
            int mapBinding = 0;
            int logBinding = 0;

            if (rawFallback && !TryReserveRawBindings(resourceManager, operation, out mapBinding, out logBinding))
            {
                gpuAccessor.Log($"Global memory operation \"{operation.Inst}\": no storage buffer slot left for the memory pool table, the loaded pointer's path is dropped.");

                rawFallback = false;

                if (gtsContext.TryGetFunctionId(operation, isMultiTarget: true, targetCbs, out functionId))
                {
                    return true;
                }
            }

            if (rawFallback)
            {
                GenerateRawAccess(context, resourceManager, operation, mapBinding, logBinding);
            }

            bool returnsValue = operation.Dest != null;

            if (returnsValue)
            {
                context.Return(MissedAccessResult(operation));
            }
            else
            {
                context.Return();
            }

            string functionName = GetFunctionName(operation, isMultiTarget: true, targetCbs) + (rawFallback ? "Raw" : string.Empty);

            Function function = new(
                ControlFlowGraph.Create(context.GetOperations()).Blocks,
                functionName,
                returnsValue,
                inArgumentsCount,
                0);

            functionId = gtsContext.AddFunction(operation, isMultiTarget: true, targetCbs, function, rawFallback);

            return true;
        }

        // nxnative: the memory pool table the host binds for raw global memory (dmsh_abi.h DMSH_GMEM_MAP_*): a storage buffer reserved under this sentinel constant buffer
        // slot, which no constant buffer of the game has (dmsh_build.py turns it into DMSH_KIND_GMEM_MAP). 1 << GmemMapLog2 entries of GmemMapEntryWords words each,
        // {start lo, start hi, end lo, end hi, delta lo, delta hi, 0, 0}, sorted by start; entry 0 is empty (start 0, end 0) and unused entries start at ~0
        public const int GmemMapCbSlot = 0xff;
        private const int GmemMapLog2 = 12;
        private const int GmemMapEntryWords = 8;

        // nxnative: the write log (dmsh_abi.h DMSH_GMEM_LOG_*), reserved under the same sentinel slot at offset 1: the set of guest pages (address >> 12) the stores and atomics wrote,
        // as an open-addressing hash set of 1 << GmemLogLog2 words from word 1 (0 = empty), word 0 set when a page found no free slot in GmemLogProbes tries. The host cannot know where
        // a store through a loaded pointer lands before the GPU runs it; it learns the pages from the log. A set, not a list: one draw of Donkey Kong Bananza stores 7,325 times into a few dozen pages
        private const int GmemLogCbOffset = 1;

        // nxnative: the shared memory spill buffer (StructuredIr/SharedSpillInfo.cs, dmsh_abi.h DMSH_SHARED_SPILL_CB_OFFSET), reserved under the same sentinel slot at offset 2
        public const int SharedSpillCbOffset = 2;
        private const int GmemLogLog2 = 10;
        private const int GmemLogProbes = 8;

        // nxnative: a global memory access whose address the search traced to no storage buffer, an address the shader loaded from memory (Donkey Kong Bananza: gsys's vertex
        // shader that resets the terrain's indirect draw records reads each record's address from a storage buffer). Ryujinx drops such an access (a load reads 0). Here it
        // goes to the address itself: a branchless binary search finds the host's pool holding it, the address moves by that pool's delta (its Metal GPU address minus its
        // guest address) and is accessed through a physical storage buffer pointer. An address in no pool is still dropped (a load and an atomic return 0, a
        // compare-and-swap its comparator: MissedAccessResult)
        private static bool TryGenerateRawStorageOp(
            GtsContext gtsContext,
            ResourceManager resourceManager,
            IGpuAccessor gpuAccessor,
            Operation operation,
            out int functionId)
        {
            functionId = 0;

            if (!CanUseRawStorageOp(operation))
            {
                gpuAccessor.Log($"Global memory operation \"{operation.Inst}\" on a small integer traced to no storage buffer: not implemented.");
                return false;
            }

            if (!TryReserveRawBindings(resourceManager, operation, out int mapBinding, out int logBinding))
            {
                return false;
            }

            int inArgumentsCount = 2;

            if (operation.Inst == Instruction.AtomicCompareAndSwap)
            {
                inArgumentsCount = 4;
            }
            else if (operation.Inst == Instruction.Store || operation.Inst.IsAtomic())
            {
                inArgumentsCount = 3;
            }

            EmitterContext context = new();

            GenerateRawAccess(context, resourceManager, operation, mapBinding, logBinding);

            bool returnsValue = operation.Dest != null;

            if (returnsValue)
            {
                context.Return(MissedAccessResult(operation));
            }
            else
            {
                context.Return();
            }

            Function function = new(
                ControlFlowGraph.Create(context.GetOperations()).Blocks,
                GetFunctionName(operation, isMultiTarget: true, []) + "Raw",
                returnsValue,
                inArgumentsCount,
                0);

            functionId = gtsContext.AddFunction(operation, isMultiTarget: true, [], function);

            return true;
        }

        // nxnative: the raw path takes every access but an atomic on a small integer (a CAS loop on its word is not written)
        private static bool CanUseRawStorageOp(Operation operation)
        {
            return !(IsSmallInt(operation.StorageKind) && operation.Inst.IsAtomic());
        }

        // nxnative: the raw path's storage buffers: the memory pool table, and the write log when the access writes
        private static bool TryReserveRawBindings(ResourceManager resourceManager, Operation operation, out int mapBinding, out int logBinding)
        {
            logBinding = 0;

            if (!resourceManager.TryGetStorageBufferBinding(GmemMapCbSlot, 0, write: false, out mapBinding))
            {
                return false;
            }

            bool writes = operation.Inst == Instruction.Store || operation.Inst.IsAtomic();

            if (writes && !resourceManager.TryGetStorageBufferBinding(GmemMapCbSlot, GmemLogCbOffset, write: true, out logBinding))
            {
                return false;
            }

            resourceManager.Properties.UsesPhysicalPointers = true;

            return true;
        }

        // nxnative: the raw path's body, in a helper whose arguments are the address (low, high) and the operation's values (as the multi-target helpers'): the pool
        // lookup, the page logged for a write, the access and its return. An address in no pool falls through to the code after it (the caller's miss return)
        private static void GenerateRawAccess(EmitterContext context, ResourceManager resourceManager, Operation operation, int mapBinding, int logBinding)
        {
            bool isSmall = IsSmallInt(operation.StorageKind);
            bool writes = operation.Inst == Instruction.Store || operation.Inst.IsAtomic();

            Operand addrLow = Argument(0);
            Operand addrHigh = Argument(1);

            Operand MapWord(Operand entry, int word)
            {
                return context.Load(StorageKind.StorageBuffer, mapBinding, Const(0), context.IAdd(entry, Const(word)));
            }

            // Port of iOS V22's per-invocation last-segment cache. Every valid
            // hit bypasses the map and binary search, regardless of pool number.
            // Separate cache words per raw access helper, SPIR-V Private zero-init.
            // A miss still uses the V10.1 pool-1 shortcut then full binary search.
            bool cacheLast = Environment.GetEnvironmentVariable("DMSH_GMEM_LAST1") == "1";
            bool fastPool = Environment.GetEnvironmentVariable("DMSH_GMEM_FAST1") == "1";
            bool extendedMap = Environment.GetEnvironmentVariable("DMSH_GMEM_MAP_8192") == "1";
            Operand selected = fastPool || cacheLast ? Local() : null;
            Operand afterSearch = fastPool || cacheLast ? Label() : null;
            Operand chosen = cacheLast ? Label() : null;
            Operand cachedDeltaLow = cacheLast ? Local() : null;
            Operand cachedDeltaHigh = cacheLast ? Local() : null;
            int[] last = cacheLast ? new int[7] : null;
            Operand CacheWord(int k) => context.Load(StorageKind.LocalMemory, last[k]);
            if (cacheLast)
            {
                for (int k = 0; k < last.Length; k++)
                {
                    last[k] = resourceManager.AddRawLastEntryMemory();
                }
                Operand geStart = context.BitwiseOr(
                    context.ICompareLessUnsigned(CacheWord(2), addrHigh),
                    context.BitwiseAnd(context.ICompareEqual(CacheWord(2), addrHigh),
                                       context.ICompareLessOrEqualUnsigned(CacheWord(1), addrLow)));
                Operand ltEnd = context.BitwiseOr(
                    context.ICompareLessUnsigned(addrHigh, CacheWord(4)),
                    context.BitwiseAnd(context.ICompareEqual(addrHigh, CacheWord(4)),
                                       context.ICompareLessUnsigned(addrLow, CacheWord(3))));
                context.Copy(selected, CacheWord(0));
                context.Copy(cachedDeltaLow, CacheWord(5));
                context.Copy(cachedDeltaHigh, CacheWord(6));
                context.BranchIfTrue(chosen, context.BitwiseAnd(geStart, ltEnd));
            }

            // V10.1 full 64-bit bounds-checked pool-1 fast path is preserved.
            if (fastPool)
            {
                Operand first = Const(GmemMapEntryWords); // first nonempty pool
                Operand startLo = MapWord(first, 0);
                Operand startHi = MapWord(first, 1);
                Operand stopLo = MapWord(first, 2);
                Operand stopHi = MapWord(first, 3);
                Operand geStart = context.BitwiseOr(
                    context.ICompareLessUnsigned(startHi, addrHigh),
                    context.BitwiseAnd(context.ICompareEqual(startHi, addrHigh), context.ICompareLessOrEqualUnsigned(startLo, addrLow)));
                Operand ltEnd = context.BitwiseOr(
                    context.ICompareLessUnsigned(addrHigh, stopHi),
                    context.BitwiseAnd(context.ICompareEqual(addrHigh, stopHi), context.ICompareLessUnsigned(addrLow, stopLo)));
                Operand slow = Label();
                context.BranchIfFalse(slow, context.BitwiseAnd(geStart, ltEnd));
                context.Copy(selected, Const(1));
                context.Branch(afterSearch);
                context.MarkLabel(slow);
            }

            // The last entry whose start is at or below the address (entry 0 starts at 0, so there always is one)
            Operand index = Const(0);

            int mapLog2 = extendedMap ? 13 : GmemMapLog2;
            for (int step = 1 << (mapLog2 - 1); step != 0; step >>= 1)
            {
                Operand candidate = context.IAdd(index, Const(step));
                Operand entry = context.IMultiply(candidate, Const(GmemMapEntryWords));
                Operand startLow = MapWord(entry, 0);
                Operand startHigh = MapWord(entry, 1);

                Operand atOrBelow = context.BitwiseOr(
                    context.ICompareLessUnsigned(startHigh, addrHigh),
                    context.BitwiseAnd(context.ICompareEqual(startHigh, addrHigh), context.ICompareLessOrEqualUnsigned(startLow, addrLow)));

                index = context.ConditionalSelect(atOrBelow, candidate, index);
            }
            if (fastPool || cacheLast)
            {
                context.Copy(selected, index);
                context.MarkLabel(afterSearch);
                index = selected;
            }

            Operand found = context.IMultiply(index, Const(GmemMapEntryWords));
            Operand endLow = MapWord(found, 2);
            Operand endHigh = MapWord(found, 3);

            Operand inPool = context.BitwiseOr(
                context.ICompareLessUnsigned(addrHigh, endHigh),
                context.BitwiseAnd(context.ICompareEqual(addrHigh, endHigh), context.ICompareLessUnsigned(addrLow, endLow)));

            Operand lblSkip = Label();
            context.BranchIfFalse(lblSkip, inPool);

            if (cacheLast)
            {
                // Cache only a validated [start,end) region. A miss through the
                // map retains the preceding valid entry so no bogus pointers
                // are ever returned for unmapped guest addresses.
                context.Copy(cachedDeltaLow, MapWord(found, 4));
                context.Copy(cachedDeltaHigh, MapWord(found, 5));
                context.Store(StorageKind.LocalMemory, last[0], index);
                context.Store(StorageKind.LocalMemory, last[1], MapWord(found, 0));
                context.Store(StorageKind.LocalMemory, last[2], MapWord(found, 1));
                context.Store(StorageKind.LocalMemory, last[3], endLow);
                context.Store(StorageKind.LocalMemory, last[4], endHigh);
                context.Store(StorageKind.LocalMemory, last[5], cachedDeltaLow);
                context.Store(StorageKind.LocalMemory, last[6], cachedDeltaHigh);
                context.MarkLabel(chosen);
            }

            if (writes)
            {
                // A page in a pool is never 0 (the guest's first page is not mapped), so 0 marks an empty slot
                Operand page = context.BitwiseOr(context.ShiftLeft(addrHigh, Const(20)), context.ShiftRightU32(addrLow, Const(12)));
                Operand hash = context.ShiftRightU32(context.IMultiply(page, Const(unchecked((int)0x9e3779b1))), Const(32 - GmemLogLog2));

                Operand lblLogged = Label();

                for (int probe = 0; probe < GmemLogProbes; probe++)
                {
                    Operand slot = context.IAdd(context.BitwiseAnd(context.IAdd(hash, Const(probe)), Const((1 << GmemLogLog2) - 1)), Const(1));
                    Operand old = context.AtomicCompareAndSwap(StorageKind.StorageBuffer, logBinding, Const(0), slot, Const(0), page);
                    context.BranchIfTrue(lblLogged, context.BitwiseOr(context.ICompareEqual(old, Const(0)), context.ICompareEqual(old, page)));
                }

                context.Store(StorageKind.StorageBuffer, logBinding, Const(0), Const(0), Const(1));
                context.MarkLabel(lblLogged);
            }

            // A small integer is read or written in its 32-bit word
            Operand wordLow = isSmall ? context.BitwiseAnd(addrLow, Const(~3)) : addrLow;
            Operand hostLow = context.IAdd(wordLow, cacheLast ? cachedDeltaLow : MapWord(found, 4));
            Operand carry = context.ConditionalSelect(context.ICompareLessUnsigned(hostLow, wordLow), Const(1), Const(0));
            Operand hostHigh = context.IAdd(context.IAdd(addrHigh, cacheLast ? cachedDeltaHigh : MapWord(found, 5)), carry);

            Operand resultValue = null;

            if (operation.Inst == Instruction.Load)
            {
                resultValue = context.Load(StorageKind.GlobalMemory, hostLow, hostHigh);

                if (isSmall)
                {
                    Operand bitOffset = HelperFunctionManager.GetBitOffset(context, addrLow);

                    resultValue = operation.StorageKind switch
                    {
                        StorageKind.GlobalMemoryS8 => context.BitfieldExtractS32(context.ShiftRightS32(resultValue, bitOffset), Const(0), Const(8)),
                        StorageKind.GlobalMemoryS16 => context.BitfieldExtractS32(context.ShiftRightS32(resultValue, bitOffset), Const(0), Const(16)),
                        StorageKind.GlobalMemoryU8 => context.BitwiseAnd(context.ShiftRightU32(resultValue, bitOffset), Const(byte.MaxValue)),
                        _ => context.BitwiseAnd(context.ShiftRightU32(resultValue, bitOffset), Const(ushort.MaxValue)),
                    };
                }
            }
            else if (operation.Inst == Instruction.Store)
            {
                Operand value = Argument(2);

                if (isSmall)
                {
                    int bitSize = operation.StorageKind is StorageKind.GlobalMemoryS8 or StorageKind.GlobalMemoryU8 ? 8 : 16;
                    Operand bitOffset = HelperFunctionManager.GetBitOffset(context, addrLow);

                    GenerateRawCasLoop(context, hostLow, hostHigh, (memValue) => context.BitfieldInsert(memValue, value, bitOffset, Const(bitSize)));
                }
                else
                {
                    context.Store(StorageKind.GlobalMemory, hostLow, hostHigh, value);
                }
            }
            else if (operation.Inst == Instruction.AtomicCompareAndSwap)
            {
                resultValue = context.AtomicCompareAndSwap(StorageKind.GlobalMemory, hostLow, hostHigh, Argument(2), Argument(3));
            }
            else if (operation.Inst.IsAtomicFloat())
            {
                Operand value = Argument(2);

                resultValue = GenerateRawCasLoop(context, hostLow, hostHigh, (memValue) => HelperFunctionManager.GenerateAtomicFloatOp(context, operation.Inst, memValue, value));
            }
            else
            {
                resultValue = context.Add(operation.Inst, StorageKind.GlobalMemory, Local(), hostLow, hostHigh, Argument(2));
            }

            if (resultValue != null)
            {
                context.Return(resultValue);
            }
            else
            {
                context.Return();
            }

            context.MarkLabel(lblSkip);
        }

        // nxnative: what an access that reaches no memory returns (an address in no storage buffer of a multi-target function, or in no pool of the raw path's table):
        // 0 for a load or an atomic, the comparator for a compare-and-swap (Lichii a6e5217, #140). The guest's CAS loops retry while the returned value differs from
        // the comparator; 0 would keep one with a non-zero comparator spinning forever, a likely device lost on Adreno
        private static Operand MissedAccessResult(Operation operation)
        {
            return operation.Inst == Instruction.AtomicCompareAndSwap ? Argument(2) : Const(0);
        }

        // nxnative: a compare-and-swap loop on the word at a physical storage buffer address (the raw path), as HelperFunctionManager.GenerateCasLoop
        private static Operand GenerateRawCasLoop(EmitterContext context, Operand hostLow, Operand hostHigh, Func<Operand, Operand> opCallback)
        {
            return HelperFunctionManager.GenerateCasLoop(
                context,
                () => context.Load(StorageKind.GlobalMemory, hostLow, hostHigh),
                (expected, newValue) => context.AtomicCompareAndSwap(StorageKind.GlobalMemory, hostLow, hostHigh, expected, newValue),
                opCallback);
        }

        private static uint PackCbSlotAndOffset(int cbSlot, int cbOffset)
        {
            return (uint)((ushort)cbSlot | ((ushort)cbOffset << 16));
        }

        private static (int, int) UnpackCbSlotAndOffset(uint packed)
        {
            return ((ushort)packed, (ushort)(packed >> 16));
        }

        private static string GetFunctionName(Operation baseOp, bool isMultiTarget, IReadOnlyList<uint> targetCbs)
        {
            StringBuilder nameBuilder = new();
            nameBuilder.Append(baseOp.Inst.ToString());

            nameBuilder.Append(baseOp.StorageKind switch
            {
                StorageKind.GlobalMemoryS8 => "S8",
                StorageKind.GlobalMemoryS16 => "S16",
                StorageKind.GlobalMemoryU8 => "U8",
                StorageKind.GlobalMemoryU16 => "U16",
                _ => string.Empty,
            });

            if (isMultiTarget)
            {
                nameBuilder.Append("Multi");
            }

            foreach (uint targetCb in targetCbs)
            {
                (int sbCbSlot, int sbCbOffset) = UnpackCbSlotAndOffset(targetCb);

                nameBuilder.Append($"_c{sbCbSlot}o{sbCbOffset}");
            }

            return nameBuilder.ToString();
        }

        private static bool TryGenerateStorageOp(
            ResourceManager resourceManager,
            TargetLanguage targetLanguage,
            EmitterContext context,
            Instruction inst,
            StorageKind storageKind,
            Operand offset,
            Operand compare,
            Operand value,
            SearchResult result,
            out Operand resultValue)
        {
            resultValue = null;
            bool isStore = inst.IsAtomic() || inst == Instruction.Store;

            if (!resourceManager.TryGetStorageBufferBinding(result.SbCbSlot, result.SbCbOffset, isStore, out int binding))
            {
                return false;
            }

            Operand wordOffset = context.ShiftRightU32(offset, Const(2));

            if (inst.IsAtomic())
            {
                if (IsSmallInt(storageKind))
                {
                    throw new NotImplementedException();
                }

                switch (inst)
                {
                    case Instruction.AtomicAdd:
                        resultValue = context.AtomicAdd(StorageKind.StorageBuffer, binding, Const(0), wordOffset, value);
                        break;
                    case Instruction.AtomicAnd:
                        resultValue = context.AtomicAnd(StorageKind.StorageBuffer, binding, Const(0), wordOffset, value);
                        break;
                    case Instruction.AtomicCompareAndSwap:
                        resultValue = context.AtomicCompareAndSwap(StorageKind.StorageBuffer, binding, Const(0), wordOffset, compare, value);
                        break;
                    case Instruction.AtomicMaxS32:
                        if (targetLanguage == TargetLanguage.Spirv)
                        {
                            resultValue = context.AtomicMaxS32(StorageKind.StorageBuffer, binding, Const(0), wordOffset, value);
                        }
                        else
                        {
                            resultValue = GenerateAtomicCasLoop(context, wordOffset, binding, (memValue) =>
                            {
                                return context.IMaximumS32(memValue, value);
                            });
                        }

                        break;
                    case Instruction.AtomicMaxU32:
                        resultValue = context.AtomicMaxU32(StorageKind.StorageBuffer, binding, Const(0), wordOffset, value);
                        break;
                    case Instruction.AtomicMinS32:
                        if (targetLanguage == TargetLanguage.Spirv)
                        {
                            resultValue = context.AtomicMinS32(StorageKind.StorageBuffer, binding, Const(0), wordOffset, value);
                        }
                        else
                        {
                            resultValue = GenerateAtomicCasLoop(context, wordOffset, binding, (memValue) =>
                            {
                                return context.IMinimumS32(memValue, value);
                            });
                        }

                        break;
                    case Instruction.AtomicMinU32:
                        resultValue = context.AtomicMinU32(StorageKind.StorageBuffer, binding, Const(0), wordOffset, value);
                        break;
                    case Instruction.AtomicOr:
                        resultValue = context.AtomicOr(StorageKind.StorageBuffer, binding, Const(0), wordOffset, value);
                        break;
                    case Instruction.AtomicSwap:
                        resultValue = context.AtomicSwap(StorageKind.StorageBuffer, binding, Const(0), wordOffset, value);
                        break;
                    case Instruction.AtomicXor:
                        resultValue = context.AtomicXor(StorageKind.StorageBuffer, binding, Const(0), wordOffset, value);
                        break;
                    case Instruction.AtomicAddF32:
                    case Instruction.AtomicAddF16x2:
                        resultValue = GenerateAtomicCasLoop(context, wordOffset, binding, (memValue) =>
                        {
                            return HelperFunctionManager.GenerateAtomicFloatOp(context, inst, memValue, value);
                        });
                        break;
                }
            }
            else if (inst == Instruction.Store)
            {
                int bitSize = storageKind switch
                {
                    StorageKind.GlobalMemoryS8 or
                    StorageKind.GlobalMemoryU8 => 8,
                    StorageKind.GlobalMemoryS16 or
                    StorageKind.GlobalMemoryU16 => 16,
                    _ => 32,
                };

                if (bitSize < 32)
                {
                    Operand bitOffset = HelperFunctionManager.GetBitOffset(context, offset);

                    GenerateAtomicCasLoop(context, wordOffset, binding, (memValue) =>
                    {
                        return context.BitfieldInsert(memValue, value, bitOffset, Const(bitSize));
                    });
                }
                else
                {
                    context.Store(StorageKind.StorageBuffer, binding, Const(0), wordOffset, value);
                }
            }
            else
            {
                value = context.Load(StorageKind.StorageBuffer, binding, Const(0), wordOffset);

                if (IsSmallInt(storageKind))
                {
                    Operand bitOffset = HelperFunctionManager.GetBitOffset(context, offset);

                    switch (storageKind)
                    {
                        case StorageKind.GlobalMemoryS8:
                            value = context.ShiftRightS32(value, bitOffset);
                            value = context.BitfieldExtractS32(value, Const(0), Const(8));
                            break;
                        case StorageKind.GlobalMemoryS16:
                            value = context.ShiftRightS32(value, bitOffset);
                            value = context.BitfieldExtractS32(value, Const(0), Const(16));
                            break;
                        case StorageKind.GlobalMemoryU8:
                            value = context.ShiftRightU32(value, bitOffset);
                            value = context.BitwiseAnd(value, Const(byte.MaxValue));
                            break;
                        case StorageKind.GlobalMemoryU16:
                            value = context.ShiftRightU32(value, bitOffset);
                            value = context.BitwiseAnd(value, Const(ushort.MaxValue));
                            break;
                    }
                }

                resultValue = value;
            }

            return true;
        }

        // nxnative: retries with the value the CAS returned (HelperFunctionManager.GenerateCasLoop, Lichii PR #206)
        private static Operand GenerateAtomicCasLoop(EmitterContext context, Operand wordOffset, int binding, Func<Operand, Operand> opCallback)
        {
            return HelperFunctionManager.GenerateCasLoop(
                context,
                () => context.Load(StorageKind.StorageBuffer, binding, Const(0), wordOffset),
                (expected, newValue) => context.AtomicCompareAndSwap(StorageKind.StorageBuffer, binding, Const(0), wordOffset, expected, newValue),
                opCallback);
        }

        private static SearchResult FindUniqueBaseAddressCb(GtsContext gtsContext, BasicBlock block, Operand globalAddress, bool needsOffset)
        {
            globalAddress = Utils.FindLastOperation(globalAddress, block);

            if (globalAddress.Type == OperandType.ConstantBuffer)
            {
                return GetBaseAddressCbWithOffset(globalAddress, Const(0), 0);
            }

            Operation operation = globalAddress.AsgOp as Operation;

            if (operation == null || operation.Inst != Instruction.Add)
            {
                return FindBaseAddressCbFromMemory(gtsContext, operation, 0, needsOffset);
            }

            Operand src1 = operation.GetSource(0);
            Operand src2 = operation.GetSource(1);

            int constOffset = 0;

            if ((src1.Type == OperandType.LocalVariable && src2.Type == OperandType.Constant) ||
                (src2.Type == OperandType.LocalVariable && src1.Type == OperandType.Constant))
            {
                Operand baseAddr;
                Operand offset;

                if (src1.Type == OperandType.LocalVariable)
                {
                    baseAddr = Utils.FindLastOperation(src1, block);
                    offset = src2;
                }
                else
                {
                    baseAddr = Utils.FindLastOperation(src2, block);
                    offset = src1;
                }

                SearchResult result = GetBaseAddressCbWithOffset(baseAddr, offset, 0);
                if (result.Found)
                {
                    return result;
                }

                constOffset = offset.Value;
                operation = baseAddr.AsgOp as Operation;

                if (operation == null || operation.Inst != Instruction.Add)
                {
                    return FindBaseAddressCbFromMemory(gtsContext, operation, constOffset, needsOffset);
                }
            }

            src1 = operation.GetSource(0);
            src2 = operation.GetSource(1);

            // If we have two possible results, we give preference to the ones from
            // the driver reserved constant buffer, as those are the ones that
            // contains the base address.

            // If both are constant buffer, give preference to the second operand,
            // because constant buffer are always encoded as the second operand,
            // so the second operand will always be the one from the last instruction.
            // Unless only the first is from the driver reserved buffer: Ampere code adds uniform registers
            // (Donkey Kong Bananza's effect compute shaders: c0 storage entry + offset from c1, by UIMAD.WIDE),
            // and the IR keeps the order of their sources.

            SearchResult directResult;

            if (src1.Type == OperandType.ConstantBuffer && src2.Type == OperandType.ConstantBuffer &&
                src1.GetCbufSlot() == DriverReservedCb && src2.GetCbufSlot() != DriverReservedCb)
            {
                directResult = GetBaseAddressCbWithOffset(src1, src2, constOffset);
            }
            else if (src1.Type != OperandType.ConstantBuffer ||
                (src1.Type == OperandType.ConstantBuffer && src2.Type == OperandType.ConstantBuffer) ||
                (src2.Type == OperandType.ConstantBuffer && src2.GetCbufSlot() == DriverReservedCb))
            {
                directResult = GetBaseAddressCbWithOffset(src2, src1, constOffset);
            }
            else
            {
                directResult = GetBaseAddressCbWithOffset(src1, src2, constOffset);
            }

            if (directResult.Found)
            {
                return directResult;
            }

            // Ampere code often adds a uniform offset to a storage buffer base address in a uniform register
            // (ULDC.64 UR, c[0][...] -> UIADD3 UR, UR_off, UR) before adding the per-lane register in LDG/STG [Ra + UR],
            // nesting the constant buffer reference inside a chain of Add operations.
            return FindBaseAddressCbInAddTree(gtsContext, operation, 8);
        }

        private static SearchResult FindBaseAddressCbInAddTree(GtsContext gtsContext, Operation operation, int depth)
        {
            if (depth <= 0 || operation == null)
            {
                return SearchResult.NotFound;
            }

            if (operation.Inst != Instruction.Add)
            {
                return FindBaseAddressCbFromMemory(gtsContext, operation, 0, needsOffset: false);
            }

            SearchResult r1 = FindBaseAddressCbInAddOperand(gtsContext, operation.GetSource(0), depth - 1);
            SearchResult r2 = FindBaseAddressCbInAddOperand(gtsContext, operation.GetSource(1), depth - 1);

            if (r1.Found && r2.Found)
            {
                if (r1.SbCbSlot == DriverReservedCb && r2.SbCbSlot == DriverReservedCb && r1.SbCbOffset != r2.SbCbOffset)
                {
                    return SearchResult.NotFound;
                }

                return r1.SbCbSlot == DriverReservedCb && r2.SbCbSlot != DriverReservedCb ? r1 : r2;
            }

            return r1.Found ? r1 : r2;
        }

        private static SearchResult FindBaseAddressCbInAddOperand(GtsContext gtsContext, Operand src, int depth)
        {
            if (src.Type == OperandType.ConstantBuffer)
            {
                return GetBaseAddressCbWithOffset(src, null, 0);
            }

            if (src.AsgOp is Operation childOp)
            {
                return FindBaseAddressCbInAddTree(gtsContext, childOp, depth);
            }

            return SearchResult.NotFound;
        }

        // nxnative: → whether the operand leads to a phi (one queued now or one already visited), which TryGenerateMultiTargetStorageOp takes as a path still being followed
        private static bool EnqueueAddPhis(Operand operand, Queue<PhiNode> phis, HashSet<PhiNode> visited, int depth)
        {
            if (depth <= 0 || operand == null)
            {
                return false;
            }

            if (operand.AsgOp is PhiNode phi)
            {
                if (visited.Add(phi))
                {
                    phis.Enqueue(phi);
                }

                return true;
            }
            else if (operand.AsgOp is Operation op && op.Inst == Instruction.Add)
            {
                bool left = EnqueueAddPhis(op.GetSource(0), phis, visited, depth - 1);
                bool right = EnqueueAddPhis(op.GetSource(1), phis, visited, depth - 1);

                return left || right;
            }

            return false;
        }

        private static SearchResult FindBaseAddressCbFromMemory(GtsContext gtsContext, Operation operation, int constOffset, bool needsOffset)
        {
            if (operation != null)
            {
                if (TryGetMemoryOffsets(operation, out LsMemoryType type, out Operand bo, out int co) &&
                    gtsContext.TryGetMemoryTargetCb(type, bo, co, out SearchResult result) &&
                    (result.Offset != null || !needsOffset))
                {
                    if (constOffset != 0)
                    {
                        return new SearchResult(
                            result.SbCbSlot,
                            result.SbCbOffset,
                            result.Offset,
                            result.ConstOffset + constOffset);
                    }

                    return result;
                }
            }

            return SearchResult.NotFound;
        }

        private static SearchResult GetBaseAddressCbWithOffset(Operand baseAddress, Operand offset, int constOffset)
        {
            if (baseAddress.Type == OperandType.ConstantBuffer)
            {
                int sbCbSlot = baseAddress.GetCbufSlot();
                int sbCbOffset = baseAddress.GetCbufOffset();

                // We require the offset to be aligned to 1 word (64 bits),
                // since the address size is 64-bit and the GPU only supports aligned memory access.
                if ((sbCbOffset & 1) == 0)
                {
                    return new SearchResult(sbCbSlot, sbCbOffset, offset, constOffset);
                }
            }

            return SearchResult.NotFound;
        }

        private static bool TryGetMemoryOffsets(Operation operation, out LsMemoryType type, out Operand baseOffset, out int constOffset)
        {
            baseOffset = null;

            if (operation.Inst is Instruction.Load or Instruction.Store)
            {
                if (operation.StorageKind == StorageKind.SharedMemory)
                {
                    type = LsMemoryType.Shared;
                    return TryGetSharedMemoryOffsets(operation, out baseOffset, out constOffset);
                }
                else if (operation.StorageKind == StorageKind.LocalMemory)
                {
                    type = LsMemoryType.Local;
                    return TryGetLocalMemoryOffset(operation, out constOffset);
                }
            }

            type = default;
            constOffset = 0;
            return false;
        }

        private static bool TryGetSharedMemoryOffsets(Operation operation, out Operand baseOffset, out int constOffset)
        {
            baseOffset = null;
            constOffset = 0;

            // The byte offset is right shifted by 2 to get the 32-bit word offset,
            // so we want to get the byte offset back, since each one of those word
            // offsets are a new "local variable" which will not match.

            if (operation.GetSource(1).AsgOp is Operation shiftRightOp &&
                shiftRightOp.Inst == Instruction.ShiftRightU32 &&
                shiftRightOp.GetSource(1).Type == OperandType.Constant &&
                shiftRightOp.GetSource(1).Value == 2)
            {
                baseOffset = shiftRightOp.GetSource(0);
            }

            // Check if we have a constant offset being added to the base offset.

            if (baseOffset?.AsgOp is Operation addOp && addOp.Inst == Instruction.Add)
            {
                Operand src1 = addOp.GetSource(0);
                Operand src2 = addOp.GetSource(1);

                if (src1.Type == OperandType.Constant && src2.Type == OperandType.LocalVariable)
                {
                    constOffset = src1.Value;
                    baseOffset = src2;
                }
                else if (src1.Type == OperandType.LocalVariable && src2.Type == OperandType.Constant)
                {
                    baseOffset = src1;
                    constOffset = src2.Value;
                }
            }

            return baseOffset != null && baseOffset.Type == OperandType.LocalVariable;
        }

        private static bool TryGetLocalMemoryOffset(Operation operation, out int constOffset)
        {
            Operand offset = operation.GetSource(1);

            if (offset.Type == OperandType.Constant)
            {
                constOffset = offset.Value;
                return true;
            }

            constOffset = 0;
            return false;
        }
    }
}
