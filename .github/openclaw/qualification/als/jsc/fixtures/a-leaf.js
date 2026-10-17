export const before = $vm.asyncContext();
await Promise.resolve();
export const after = $vm.asyncContext();
