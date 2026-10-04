async function leaf() {
await Promise.resolve();
return new Error().stack;
}
async function parent() {
return await leaf();
}
const trace = await parent();
const parentFrame = trace.split("\n").find(line => /\bparent(?:\s|@|\()/.test(line));
const position = /:(\d+):(\d+)\)?$/.exec(parentFrame);
if (!position || +position[1] !== 6 || +position[2] !== 8)
    throw new Error(JSON.stringify({ expected: [6, 8], trace }));
