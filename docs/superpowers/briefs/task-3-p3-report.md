# Task 3 Phase 3: Wire ResearchAgent and FileAgent into Brain Dispatch

## Completion Summary

Successfully wired ResearchAgent and FileAgent into brain.py's `_try_agent_dispatch()` method and added comprehensive router tests for both agents.

## Changes Made

### 1. Modified `core/brain.py` (line ~5953)
- Updated `_try_agent_dispatch()` to handle "research" and "file" intents
- Added ResearchAgent dispatch for "research" intent
- Added FileAgent dispatch for "file" intent
- Replaced placeholder comment with active dispatch logic

### 2. Modified `tests/agents/test_router.py`
- Appended new `TestResearchAndFileRouting` test class with 8 comprehensive tests
- Tests cover research keyword patterns (research everything, latest news, deep dive into)
- Tests cover file keyword patterns (.pdf, .docx, file extensions, document references, contract terms)
- All tests pass with router's existing keyword matching

### 3. Modified `tests/test_brain_routing.py`
- Updated `test_unimplemented_agent_falls_through_to_instant()` → `test_research_task_routes_to_research_agent()`
- Test now properly mocks ResearchAgent.run() instead of expecting fallthrough behavior
- Aligns with pattern used for screen_agent and browser_agent tests

## Test Results

### Router Tests (test_router.py)
- All 28 tests passing (20 existing + 8 new)
- Research routing: 3 tests (everything, latest news, deep dive patterns)
- File routing: 5 tests (pdf, docx, xlsx keywords; document & contract references)

### Full Test Suite
- **170 total tests passing** (162 baseline + 8 new router tests)
- No test breakage
- All agent dispatch routing verified

## Implementation Details

The router already had `_RESEARCH_KEYWORDS` and `_FILE_KEYWORDS` defined and integrated into `_LABEL_KEYWORDS`, so no router changes were needed. The implementation simply:

1. Checked intent classification (already working)
2. Added conditional branches to dispatch to the appropriate agents
3. Ensured ResearchAgent and FileAgent are imported and instantiated on demand

## Verification Checklist

- [x] Router classifies research and file intents correctly
- [x] ResearchAgent dispatch integrated
- [x] FileAgent dispatch integrated  
- [x] New router tests all pass (8/8)
- [x] Existing tests unbroken (162 → 170)
- [x] Full test suite passes
- [x] Changes committed to git

## Commits

```
812ec2f feat: wire ResearchAgent and FileAgent into brain dispatch
```

---

**Task Status:** ✅ COMPLETE  
**Date:** 2026-06-23  
**Test Coverage:** 170/170 passing
