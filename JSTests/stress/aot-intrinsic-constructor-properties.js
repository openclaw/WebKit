//@ runDefault("-m", "--compileMainScriptAheadOfTime=1")

function isInteger(value) { return Number.isInteger(value | 0); }
function fromCode(value) { return String.fromCharCode(value | 0); }

for (let value = 65; value < 75; ++value) {
    if (!isInteger(value) || fromCode(value).charCodeAt(0) !== value)
        throw new Error("Wrong result from a constructor's static method");
}

for (const [name, intrinsic] of [["isInteger", "Number.isInteger"], ["fromCode", "String.fromCharCode"]]) {
    if (!aotRemarks(name).includes("lowered-builtin:" + intrinsic))
        throw new Error("The intrinsic catalog lost " + intrinsic);
}
