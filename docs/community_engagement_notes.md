# Paperless-NGX Community Engagement Notes

**Date:** February 8, 2026
**Purpose:** Track ongoing discussions related to OCR Broker architecture and identify participation opportunities

---

## Active Discussions Summary

### 1. Discussion #12029: Support a self-hostable remote OCR service

**Status:** ✅ Participated
**Author:** @datenzar
**Key Proposal:** Generic provider/plugin-style OCR architecture

**Our Contribution:**

-   Posted detailed comment explaining the "OCR Broker" concept
-   Positioned it as a solution that keeps Paperless in control while allowing external delegation
-   Proposed compatibility with @datenzar's `ocr-service` as a "Remote Engine" backend
-   Tagged @shamoon and @stumpylog for maintainer review

**Next Actions:**

-   [ ] Wait for maintainer response (@shamoon / @stumpylog)
-   [ ] Monitor for @datenzar's reaction to our proposal
-   [ ] Prepare to link to PR when broker infrastructure is ready

---

### 2. Discussion #11939: Hardware Accelerated OCR Workers (NPU/GPU)

**Status:** ⏳ Opportunity for participation
**Author:** @Ncard00123
**Key Request:** Support for GPU/NPU hardware acceleration

**Why Participate:**
This is a perfect use case for the OCR Broker architecture. It demonstrates how our routing layer enables hardware-specific backends without burdening the core codebase.

**Draft Response (Ready to Post):**

> @Ncard00123 This is exactly one of the use cases I'm targeting with a new **"OCR Broker"** architecture I'm working on (see discussion #12029).
>
> The idea is to decouple the OCR logic so that Paperless doesn't need to know _how_ the OCR happens, just _where_ to send it.
>
> In my current POC, I can define a rule like:
>
> -   **Standard Docs:** Process locally with Tesseract (CPU).
> -   **Heavy/Handwritten Docs:** Route to a "Remote Engine" (like Ollama/vLLM running on a GPU node) to use a Vision Model.
>
> This allows you to have "Hardware Accelerated Workers" without Paperless needing to manage GPU drivers or heavy Docker containers itself.

**Next Actions:**

-   [ ] Post comment linking #12029 as solution approach
-   [ ] Emphasize how broker enables GPU offloading without core complexity

---

### 3. Discussion #12023: Add alternative LLM based OCR

**Status:** ⏳ High-value participation opportunity
**Author:** @flobernd
**Maintainer Response:** @shamoon explicitly endorsed "pluggable" architecture

**Why Participate (CRITICAL):**
This is a direct endorsement of our approach from a maintainer. @shamoon wrote: _"we will continue to opt for some kind of 'pluggable' [architecture] whereby these tasks are offloaded to other tools."_

This validates our OCR Broker direction and gives us authority to proceed.

**Draft Response (Ready to Post):**

> @flobernd @shamoon I've been working on exactly this "pluggable" architecture mentioned above.
>
> I currently have a working POC of an **OCR Broker** that allows plugging in different backends. I've successfully implemented an **Ollama backend** that lets you use local Vision Models (like `minicpm-v-2.6` or `qwen2-vl`) for OCR, specifically targeting handwritten documents where Tesseract struggles.
>
> The architecture keeps the core lightweight but allows you to route specific documents (e.g., via Mail Rule or Tag) to these heavier LLM backends only when necessary.
>
> I've detailed the architecture in #12029 and am preparing a minimal PR for the broker infrastructure to enable exactly these kinds of plugins.

**Next Actions:**

-   [ ] Post comment confirming we are building what @shamoon described
-   [ ] Reference our Ollama integration as proof-of-concept
-   [ ] Link back to #12029 for detailed architecture
-   [ ] This validates our approach - use this thread as reference when submitting PR

---

## Strategic Overview

### Our Positioning

We are building a **middle-ground solution** that satisfies multiple community needs:

1. **For #12029 (datenzar):** Our Broker can route to external services (like his ocr-service) as "Remote Engines"
2. **For #11939 (NPU/GPU):** Broker enables hardware-specific backends without core complexity
3. **For #12023 (LLM OCR):** Broker provides the "pluggable" architecture @shamoon requested

### Message Consistency

Key talking points across all discussions:

-   **"Pluggable"** - matches @shamoon's terminology
-   **"Minimal core changes"** - addresses maintainer concerns about complexity
-   **"Workflow-aware routing"** - our unique value proposition vs. external routers
-   **"Local & remote backends"** - shows flexibility

### PR Strategy

When we submit the broker PR, we can reference:

-   #12029: Shows community demand for provider architecture
-   #12023: Shows maintainer endorsement of "pluggable" approach
-   #11939: Shows hardware acceleration use case

This creates a compelling case that our PR addresses validated community needs.

---

## Related Resources

### External Projects Mentioned

-   **paperless-gpt** - Community sidecar for AI processing (mentioned in #11939)
-   **ocr-service** (OCRBridge) - @datenzar's remote OCR POC (#12029)
-   **local-llm-pdf-ocr** - Blog post and repo for LLM OCR technique (#12023)

### Our Implementation Status

-   ✅ POC tested with Docling and Ollama backends
-   ✅ Workflow routing working
-   ✅ Tesseract adapter (default behavior preserved)
-   🔄 Preparing PR for broker infrastructure (minimal, no new heavy deps)

---

## Next Steps Priority

1. **Post in #12023** (LLM OCR) - This has maintainer buy-in, highest value
2. **Post in #11939** (Hardware acceleration) - Good synergy with #12023 comment
3. **Wait for #12029 response** - Already engaged, let conversation develop
4. **Monitor for new discussions** - Watch for other "OCR plugin" requests

---

_Last updated: February 8, 2026_
