using Ryujinx.Graphics.Shader.IntermediateRepresentation;
using Ryujinx.Graphics.Shader.Translation.Optimizations;
using System.Collections.Generic;
using System.Diagnostics;

using static Ryujinx.Graphics.Shader.IntermediateRepresentation.OperandHelper;

namespace Ryujinx.Graphics.Shader.Translation.Transforms
{
    // nxnative: a float atomic on shared memory (ATOMS / Maxwell ATOMS .ADD.F32.FTZ.RN or .F16x2) becomes a call to a compare-and-swap loop, on every target: the
    // library is built offline and cannot count on the device's shaderSharedFloat32AtomicAdd (global memory: GlobalToStorage)
    class SharedAtomicFloatCas : ITransformPass
    {
        public static bool IsEnabled(IGpuAccessor gpuAccessor, ShaderStage stage, TargetLanguage targetLanguage, FeatureFlags usedFeatures)
        {
            return usedFeatures.HasFlag(FeatureFlags.SharedMemory);
        }

        public static LinkedListNode<INode> RunPass(TransformContext context, LinkedListNode<INode> node)
        {
            Operation operation = (Operation)node.Value;
            HelperFunctionName name;

            if (operation.Inst == Instruction.AtomicAddF32)
            {
                name = HelperFunctionName.SharedAtomicAddF32;
            }
            else if (operation.Inst == Instruction.AtomicAddF16x2)
            {
                name = HelperFunctionName.SharedAtomicAddF16x2;
            }
            else
            {
                return node;
            }

            if (operation.StorageKind != StorageKind.SharedMemory)
            {
                return node;
            }

            Operand result = operation.Dest;
            Operand memoryId = operation.GetSource(0);
            Operand wordOffset = operation.GetSource(1);
            Operand value = operation.GetSource(2);

            Debug.Assert(memoryId.Type == OperandType.Constant);

            int functionId = context.Hfm.GetOrCreateFunctionId(name, memoryId.Value);

            Operand[] callArgs = [Const(functionId), wordOffset, value];

            LinkedListNode<INode> newNode = node.List.AddBefore(node, new Operation(Instruction.Call, 0, result, callArgs));

            Utils.DeleteNode(node, operation);

            return newNode;
        }
    }
}
