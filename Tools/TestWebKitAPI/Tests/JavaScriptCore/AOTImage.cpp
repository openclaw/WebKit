/*
 * Copyright (C) 2026 OpenClaw Foundation. All rights reserved.
 * SPDX-License-Identifier: BSD-2-Clause
 */

#include "config.h"

#if ENABLE(AOT) && CPU(ARM64)

#include "aot/AOTImage.h"
#include <JavaScriptCore/InitializeThreading.h>
#include <JavaScriptCore/Options.h>
#include <wtf/FileSystem.h>
#include <wtf/Scope.h>
#include <wtf/text/StringToIntegerConversion.h>
#include <wtf/text/WTFString.h>

namespace TestWebKitAPI {

TEST(JavaScriptCore_AOTImage, FoldedAliasesHaveFinalBodySizes)
{
    using namespace JSC;
    using namespace JSC::AOT;
    JSC::initialize();
    String path = FileSystem::createTemporaryFile("aot-map"_s);
    ASSERT_FALSE(path.isEmpty());
    auto pathBytes = path.utf8();
    auto oldPath = Options::aotMapFilePath();
    auto oldOutlining = Options::aotOutlineForTesting();
    auto cleanup = makeScopeExit([&] {
        Options::aotMapFilePath() = oldPath;
        Options::aotOutlineForTesting() = oldOutlining;
        FileSystem::deleteFile(path);
    });
    Options::aotMapFilePath() = pathBytes.data();
    Options::aotOutlineForTesting() = u8"k";

    ImageBuilder builder;
    builder.setProgramIdentifierIndices(nullptr, 1);
    constexpr unsigned originalSize = 13 * sizeof(uint32_t);
    for (unsigned index = 0; index < 2; ++index) {
        CompiledCode code;
        // Twelve ARM64 NOPs and RET: identical bodies fold, then the forced
        // outliner replaces the NOP windows with shorter calls.
        for (unsigned word = 0; word < 13; ++word) {
            uint32_t instruction = word < 12 ? 0xd503201f : 0xd65f03c0;
            code.bytes.append(std::span { reinterpret_cast<const uint8_t*>(&instruction), sizeof(instruction) });
            code.instructions.append(sizeof(instruction));
        }
        code.hasCodeAnnotations = true;
        code.info.isGenericEntrypoint = true;
        code.info.typedFunction = index;
        builder.add({ 0, index, ImageKey::typedFunction }, index, WTF::move(code), index ? "alias"_s : "canonical"_s);
    }
    for (unsigned index = 2; index < 4; ++index) {
        CompiledCode empty;
        empty.info.hasNoFrame = true;
        builder.add({ 0, index, ImageKey::typedFunction }, index, WTF::move(empty), index == 2 ? "empty"_s : "empty-alias"_s);
    }
    ASSERT_FALSE(builder.finish().isEmpty());

    auto contents = FileSystem::readEntireFile(path);
    ASSERT_TRUE(contents);
    unsigned canonicalSize = originalSize;
    unsigned aliasSize = originalSize;
    bool sawEmpty = false;
    bool sawEmptyAlias = false;
    bool sawOutlining = false;
    for (auto& line : String::fromUTF8(contents->span()).split('\n')) {
        auto fields = line.split('\t');
        if (fields[0] == "F"_s && fields.last() == "canonical"_s)
            canonicalSize = parseInteger<unsigned>(fields[3]).value();
        if (fields[0] == "A"_s && fields.last() == "alias"_s)
            aliasSize = parseInteger<unsigned>(fields[2]).value();
        if (fields[0] == "F"_s && fields.last() == "empty"_s) {
            EXPECT_EQ(parseInteger<unsigned>(fields[3]).value(), 0u);
            sawEmpty = true;
        }
        if (fields[0] == "A"_s && fields.last() == "empty-alias"_s) {
            EXPECT_EQ(parseInteger<unsigned>(fields[2]).value(), 0u);
            sawEmptyAlias = true;
        }
        sawOutlining |= fields[0] == "P"_s;
    }
    EXPECT_TRUE(sawOutlining);
    EXPECT_TRUE(sawEmpty);
    EXPECT_TRUE(sawEmptyAlias);
    EXPECT_LT(canonicalSize, originalSize);
    EXPECT_EQ(aliasSize, canonicalSize);
}

TEST(JavaScriptCore_AOTImage, OutliningPreservesReturnAddressBeforeFrameSetup)
{
    using namespace JSC;
    using namespace JSC::AOT;
    JSC::initialize();
    for (bool forced : { false, true }) {
        String path = FileSystem::createTemporaryFile("aot-prologue"_s);
        ASSERT_FALSE(path.isEmpty());
        auto pathBytes = path.utf8();
        auto oldPath = Options::aotMapFilePath();
        auto oldOutlining = Options::aotOutlineForTesting();
        auto cleanup = makeScopeExit([&] {
            Options::aotMapFilePath() = oldPath;
            Options::aotOutlineForTesting() = oldOutlining;
            FileSystem::deleteFile(path);
        });
        Options::aotMapFilePath() = pathBytes.data();
        Options::aotOutlineForTesting() = forced ? u8"k" : nullptr;

        ImageBuilder builder;
        builder.setProgramIdentifierIndices(nullptr, 1);
        for (unsigned index = 0; index < 16; ++index) {
            CompiledCode code;
            auto append = [&](uint32_t instruction) {
                code.bytes.append(std::span { reinterpret_cast<const uint8_t*>(&instruction), sizeof(instruction) });
            };
            // A generic entry may discard a collapsible caller before saving LR.
            // Turning its return-address comparison into BL destroys that LR.
            for (uint32_t instruction : std::array<uint32_t, 13> {
                     0xaa1e03ed, 0xf84001b1, 0xd2807e30, 0xf2b54230,
                     0xf2c077f0, 0xf2f22010, 0xeb10023f, 0x54000081,
                     0x910003bf, 0xa8c17bfd, 0x17fffff6, 0xa9bf7bfd, 0x910003fd })
                append(instruction);
            code.frameSetupEnd = code.bytes.size();
            for (unsigned i = 0; i < 12; ++i)
                append(0xd503201f);
            append(0x52800000 | index << 5); // Different results keep the functions distinct.
            append(0x910003bf);
            append(0xa8c17bfd);
            append(0xd65f03c0);
            code.hasCodeAnnotations = true;
            code.rareCodeMayBeOutlined = !forced;
            code.allCodeMayBeOutlined = true;
            code.info.isGenericEntrypoint = true;
            code.info.typedFunction = index;
            builder.add({ 0, index, ImageKey::typedFunction }, index, WTF::move(code), "prelude"_s);
        }
        auto image = builder.finish();
        ASSERT_FALSE(image.isEmpty());
        ImageHeader header;
        memcpy(&header, image.span().data(), sizeof(header));
        auto contents = FileSystem::readEntireFile(path);
        ASSERT_TRUE(contents);
        unsigned functions = 0;
        bool sawOutlinedCall = false;
        for (auto& line : String::fromUTF8(contents->span()).split('\n')) {
            auto fields = line.split('\t');
            if (fields[0] != "F"_s || fields.last() != "prelude"_s)
                continue;
            ++functions;
            auto start = parseInteger<unsigned>(fields[2]).value();
            auto end = start + parseInteger<unsigned>(fields[3]).value();
            bool savedReturnAddress = false;
            for (auto at = start; at < end; at += sizeof(uint32_t)) {
                uint32_t instruction;
                memcpy(&instruction, image.span().data() + header.codeOffset + at, sizeof(instruction));
                if ((instruction & 0xffc07fff) == 0xa9807bfd) // STP FP, LR, [SP, #-n]!
                    savedReturnAddress = true;
                if (instruction >> 26 == 0x25) {
                    EXPECT_TRUE(savedReturnAddress);
                    sawOutlinedCall = true;
                }
            }
            EXPECT_TRUE(savedReturnAddress);
        }
        EXPECT_EQ(functions, 16u);
        EXPECT_TRUE(sawOutlinedCall);
    }
}

} // namespace TestWebKitAPI

#endif // ENABLE(AOT) && CPU(ARM64)
