# OpenClaw WebKit fork changelog

## Unreleased

- Avoid creating an AOT instance when formatting an async JIT stack after its CodeBlock has been jettisoned.
- Prevent lazy AOT CodeBlock allocation while the collector formats weak Error stacks.
