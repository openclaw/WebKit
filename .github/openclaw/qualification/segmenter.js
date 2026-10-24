function shouldBe(actual, expected) { if (actual !== expected) throw new Error(JSON.stringify({actual, expected})); }
// containing() must agree with iteration at both halves of surrogate pairs.
{
    const inputs = [
        "a😀b",
        "Hello, world! 👍🏽 x",
        "a🇯🇵b",
        "a👨‍👩‍👧‍👦b",
        "Hi. 👍 Bye.",
        "👍🏽",
        "x\ud83d",
        "abc",
    ];
    for (const granularity of ["grapheme", "word", "sentence"]) {
        for (const input of inputs) {
            const segments = new Intl.Segmenter("en", { granularity }).segment(input);
            const expected = Array.from(segments);
            for (const direction of [1, -1]) {
                for (let index = direction > 0 ? 0 : input.length - 1; index >= 0 && index < input.length; index += direction) {
                    const result = expected.find(segment => segment.index <= index && index < segment.index + segment.segment.length);
                    const actual = segments.containing(index);
                    shouldBe(actual.segment, result.segment);
                    shouldBe(actual.index, result.index);
                    shouldBe(actual.input, input);
                    shouldBe(actual.isWordLike, result.isWordLike);
                }
            }
            shouldBe(segments.containing(-1), undefined);
            shouldBe(segments.containing(input.length), undefined);
        }
    }
}
