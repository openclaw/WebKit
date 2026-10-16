/*
 * Copyright (C) 2016-2023 Apple Inc. All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 *
 * THIS SOFTWARE IS PROVIDED BY APPLE INC. ``AS IS'' AND ANY
 * EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
 * PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL APPLE INC. OR
 * CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
 * EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
 * PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
 * PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY
 * OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE. 
 */

#include "config.h"
#include "HeapProfiler.h"

#include "HeapIterationScope.h"
#include "HeapInlines.h"
#include "HeapSnapshot.h"
#include "CodeBlock.h"
#include "StackVisitor.h"
#include "ScriptExecutable.h"
#include "SubspaceInlines.h"
#include "SymbolTable.h"
#include "VM.h"
#include <wtf/TZoneMallocInlines.h>
#include <wtf/JSONValues.h>
#include <wtf/HashMap.h>
#include <wtf/WeakRandom.h>
#include <wtf/text/MakeString.h>
#include <cmath>

namespace JSC {

WTF_MAKE_TZONE_ALLOCATED_IMPL(HeapProfiler);

struct HeapProfiler::AllocationSampling {
    WTF_MAKE_TZONE_ALLOCATED_INLINE(AllocationSampling);
public:
    struct Frame {
        String name;
        String url;
        SourceID scriptID { 0 };
        int line { -1 };
        int column { -1 };
    };
    struct Node {
        Frame frame;
        Vector<unsigned> children;
    };
    struct Sample {
        void* cell;
        double size;
        unsigned node;
        uint64_t ordinal;
        bool removed { false };
    };
    double interval;
    bool includeMajorGC;
    bool includeMinorGC;
    WeakRandom random;
    Vector<Node> nodes;
    HashMap<String, unsigned> sites;
    Vector<Sample> samples;
    HashMap<void*, Vector<unsigned>> sampledCells;
    uint64_t ordinal { 0 };
    uint64_t bytesUntilPreciseSample { 0 };
};

HeapProfiler::HeapProfiler(VM& vm)
    : m_vm(vm)
{
}

HeapProfiler::~HeapProfiler() = default;

HeapSnapshot* HeapProfiler::mostRecentSnapshot()
{
    if (m_snapshots.isEmpty())
        return nullptr;
    return m_snapshots.last().get();
}

void HeapProfiler::appendSnapshot(std::unique_ptr<HeapSnapshot> snapshot)
{
    m_snapshots.append(WTF::move(snapshot));
}

void HeapProfiler::clearSnapshots()
{
    m_snapshots.clear();
}

// analyzeVariableNameEdge needs SymbolTable entries, which cannot be faulted in from inside marking.
static void materializeLazySymbolTablesForHeapAnalysis(VM& vm)
{
    HeapIterationScope iterationScope(vm.heap);
    vm.heap.symbolTableSpace.forEachLiveCell([](HeapCell* cell, HeapCell::Kind) {
        SUPPRESS_MEMORY_UNSAFE_CAST auto* symbolTable = static_cast<SymbolTable*>(cell);
        ConcurrentJSLocker locker(symbolTable->m_lock);
        symbolTable->materializeCachedEntriesIfNeeded(locker);
    });
}

void HeapProfiler::setActiveHeapAnalyzer(HeapAnalyzer* analyzer)
{
    ASSERT(!!m_activeAnalyzer != !!analyzer);
    if (analyzer)
        materializeLazySymbolTablesForHeapAnalysis(m_vm);
    m_activeAnalyzer = analyzer;
    m_vm.setActiveHeapAnalyzer(analyzer);
}

void HeapProfiler::startAllocationSampling(double interval, bool includeMajorGC, bool includeMinorGC)
{
    ASSERT(m_vm.currentThreadIsHoldingAPILock());
    RELEASE_ASSERT(std::isfinite(interval) && interval >= 1);
    if (m_allocationSampling)
        return;
    m_allocationSampling = makeUnique<AllocationSampling>();
    auto& profile = *m_allocationSampling;
    profile.interval = interval;
    profile.includeMajorGC = includeMajorGC;
    profile.includeMinorGC = includeMinorGC;
    profile.bytesUntilPreciseSample = nextAllocationSample(1);
    profile.nodes.append({ { "(root)"_s, emptyString(), 0, -1, -1 }, { } });
    m_vm.heap.setExtraMemoryAllocationSampling(true);
    for (auto* directory = m_vm.heap.objectSpace().firstDirectory(); directory; directory = directory->nextDirectory())
        directory->configureAllocationSampling(true);
}

void HeapProfiler::stopAllocationSampling()
{
    ASSERT(m_vm.currentThreadIsHoldingAPILock());
    if (!m_allocationSampling)
        return;
    m_vm.heap.setExtraMemoryAllocationSampling(false);
    for (auto* directory = m_vm.heap.objectSpace().firstDirectory(); directory; directory = directory->nextDirectory())
        directory->configureAllocationSampling(false);
    m_allocationSampling = nullptr;
}

uint64_t HeapProfiler::nextAllocationSample(size_t cellSize)
{
    auto& profile = *m_allocationSampling;
    // Independent exponential byte intervals give each cell probability 1-exp(-size/interval).
    double count = std::floor(-std::log1p(-profile.random.get()) * profile.interval / cellSize);
    if (count >= static_cast<double>(std::numeric_limits<uint64_t>::max()))
        return std::numeric_limits<uint64_t>::max();
    return static_cast<uint64_t>(count);
}

void HeapProfiler::sampleAllocation(void* cell, size_t size)
{
    auto& profile = *m_allocationSampling;
    Vector<AllocationSampling::Frame, 128> frames;
    auto* topFrame = m_vm.topCallFrame;
    // First-call compilation can allocate after installing a CodeBlock but before
    // it has executable code or a valid call-site index. Attribute that work to its caller.
    bool skipFirstFrame = topFrame && !topFrame->isNativeCalleeFrame() && topFrame->codeBlock()
        && topFrame->codeBlock()->jitType() == JITType::None;
    // No JS objects or executable references are retained by the profiler.
    StackVisitor::visit(topFrame, m_vm, [&](StackVisitor& visitor) {
        if (auto* codeBlock = visitor->codeBlock()) {
            auto* executable = codeBlock->ownerExecutable();
            frames.append({ String::fromUTF8(codeBlock->inferredName().span()), visitor->sourceURL(), visitor->sourceID(), executable->firstLine() - 1, static_cast<int>(executable->startColumn()) - 1 });
        }
        return visitor->index() >= 127 ? IterationStatus::Done : IterationStatus::Continue;
    }, skipFirstFrame);
    unsigned parent = 0;
    for (size_t i = frames.size(); i--;) {
        auto& frame = frames[i];
        auto key = makeString(parent, ':', frame.scriptID, ':', frame.line, ':', frame.column, ':', frame.name);
        auto entry = profile.sites.add(key, profile.nodes.size());
        auto node = entry.iterator->value;
        if (entry.isNewEntry) {
            profile.nodes[parent].children.append(node);
            profile.nodes.append({ WTF::move(frame), { } });
        }
        parent = node;
    }
    // Horvitz-Thompson weighting estimates allocated bytes, including cells larger than the interval.
    double weight = size / -std::expm1(-static_cast<double>(size) / profile.interval);
    profile.sampledCells.ensure(cell, [] { return Vector<unsigned>(); }).iterator->value.append(profile.samples.size());
    profile.samples.append({ cell, weight, parent, ++profile.ordinal });
}

void HeapProfiler::samplePreciseAllocation(void* cell, size_t size)
{
    if (!m_allocationSampling)
        return;
    auto& profile = *m_allocationSampling;
    if (size <= profile.bytesUntilPreciseSample) {
        profile.bytesUntilPreciseSample -= size;
        return;
    }
    sampleAllocation(cell, size);
    // Exponential intervals are memoryless; the next budget starts at this allocation's end.
    profile.bytesUntilPreciseSample = nextAllocationSample(1);
}

void HeapProfiler::reallocateSampledCell(void* oldCell, void* newCell, size_t addedSize)
{
    if (!m_allocationSampling)
        return;
    auto& profile = *m_allocationSampling;
    // Relocation may itself have used an instrumented allocator. It is not a new allocation.
    if (oldCell != newCell) {
        for (auto index : profile.sampledCells.take(newCell))
            profile.samples[index].removed = true;
        auto indices = profile.sampledCells.take(oldCell);
        for (auto index : indices)
            profile.samples[index].cell = newCell;
        if (!indices.isEmpty())
            profile.sampledCells.set(newCell, WTF::move(indices));
    }
    if (addedSize)
        samplePreciseAllocation(newCell, addedSize);
}

void HeapProfiler::reconcileSampledAllocations(CollectionScope scope)
{
    if (!m_allocationSampling)
        return;
    auto& profile = *m_allocationSampling;
    bool include = scope == CollectionScope::Full ? profile.includeMajorGC : profile.includeMinorGC;
    profile.sampledCells.clear();
    profile.samples.removeAllMatching([&](auto& sample) {
        if (sample.removed)
            return true;
        if (!sample.cell || m_vm.heap.isMarked(sample.cell))
            return false;
        // Resolve weak addresses before sweeping can free or reuse their backing block.
        sample.cell = nullptr;
        return !include;
    });
    for (unsigned index = 0; index < profile.samples.size(); ++index) {
        if (auto* cell = profile.samples[index].cell)
            profile.sampledCells.ensure(cell, [] { return Vector<unsigned>(); }).iterator->value.append(index);
    }
}

String HeapProfiler::allocationSamplingProfile()
{
    if (!m_allocationSampling)
        return { };
    auto& profile = *m_allocationSampling;
    Vector<double> sizes(FillWith { }, profile.nodes.size(), 0);
    auto samples = JSON::Array::create();
    for (auto& sample : profile.samples) {
        if (sample.removed)
            continue;
        sizes[sample.node] += sample.size;
        auto object = JSON::Object::create();
        object->setDouble("size"_s, sample.size);
        object->setInteger("nodeId"_s, sample.node + 1);
        object->setDouble("ordinal"_s, sample.ordinal);
        samples->pushObject(WTF::move(object));
    }
    auto makeNode = [&](auto& self, unsigned index) -> Ref<JSON::Object> {
        const auto& node = profile.nodes[index];
        auto frame = JSON::Object::create();
        frame->setString("functionName"_s, node.frame.name);
        frame->setString("scriptId"_s, String::number(node.frame.scriptID));
        frame->setString("url"_s, node.frame.url);
        frame->setInteger("lineNumber"_s, node.frame.line);
        frame->setInteger("columnNumber"_s, node.frame.column);
        auto object = JSON::Object::create();
        object->setObject("callFrame"_s, WTF::move(frame));
        object->setInteger("id"_s, index + 1);
        object->setDouble("selfSize"_s, sizes[index]);
        auto children = JSON::Array::create();
        for (auto child : node.children)
            children->pushObject(self(self, child));
        object->setArray("children"_s, WTF::move(children));
        return object;
    };
    auto result = JSON::Object::create();
    result->setObject("head"_s, makeNode(makeNode, 0));
    result->setArray("samples"_s, WTF::move(samples));
    return result->toJSONString();
}

} // namespace JSC
