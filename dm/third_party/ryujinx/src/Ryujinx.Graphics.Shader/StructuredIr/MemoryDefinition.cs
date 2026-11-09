using Ryujinx.Graphics.Shader.Translation;

namespace Ryujinx.Graphics.Shader.StructuredIr
{
    readonly struct MemoryDefinition
    {
        public string Name { get; }
        public AggregateType Type { get; }
        public int ArrayLength { get; }

        // iOS V22: private state consulted before first write (raw GMEM last
        // entry cache) must start at zero for every shader invocation.
        public bool ZeroInit { get; }

        public MemoryDefinition(string name, AggregateType type, int arrayLength = 1, bool zeroInit = false)
        {
            Name = name;
            Type = type;
            ArrayLength = arrayLength;
            ZeroInit = zeroInit;
        }
    }
}
