namespace Ryujinx.Graphics.Shader.Translation
{
    enum HelperFunctionName
    {
        Invalid,

        ConvertDoubleToFloat,
        ConvertFloatToDouble,
        Hmma16816F16,
        SharedAtomicMaxS32,
        SharedAtomicMinS32,
        SharedStore8,
        SharedStore16,
        Shuffle,
        ShuffleDown,
        ShuffleUp,
        ShuffleXor,
        TexelFetchScale,
        TextureSizeUnscale,
        // nxnative: the shared memory float atomics (Instruction.AtomicAddF32), as compare-and-swap loops
        SharedAtomicAddF32,
        SharedAtomicAddF16x2,
    }
}
