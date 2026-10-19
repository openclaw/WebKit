globalThis.contextLog.push($vm.asyncContext());
$vm.setAsyncContext(['residue']);
throw Error('module throw');
