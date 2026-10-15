export const dependencyContext = $vm.asyncContext();
await Promise.resolve();
if ($vm.asyncContext() !== dependencyContext) throw Error('TLA context');
