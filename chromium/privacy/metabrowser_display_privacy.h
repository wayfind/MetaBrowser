// Copyright 2026 MetaBrowser Authors. BSD-3-Clause.
#ifndef THIRD_PARTY_BLINK_RENDERER_CORE_CANVAS_INTERVENTIONS_METABROWSER_DISPLAY_PRIVACY_H_
#define THIRD_PARTY_BLINK_RENDERER_CORE_CANVAS_INTERVENTIONS_METABROWSER_DISPLAY_PRIVACY_H_

#include <algorithm>
#include <cstdlib>
#include <cstdint>
#include <string_view>

#include "build/build_config.h"
#include "third_party/blink/public/mojom/permissions/permission.mojom-blink.h"
#include "third_party/blink/public/mojom/permissions/permission_status.mojom-blink.h"
#include "third_party/blink/public/platform/browser_interface_broker_proxy.h"
#include "third_party/blink/renderer/core/css/media_value_change.h"
#include "third_party/blink/renderer/core/frame/local_dom_window.h"
#include "third_party/blink/renderer/core/frame/local_frame.h"
#include "third_party/blink/renderer/core/page/chrome_client.h"
#include "third_party/blink/renderer/platform/heap/persistent.h"
#include "third_party/blink/renderer/platform/mojo/heap_mojo_receiver.h"
#include "third_party/blink/renderer/platform/mojo/heap_mojo_remote.h"
#include "third_party/blink/renderer/platform/supplementable.h"
#include "third_party/blink/renderer/platform/wtf/functional.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/display/screen_info.h"

namespace blink {

inline gfx::Rect MetaBrowserVirtualDisplay(LocalFrame& frame) {
  struct Size { int width; int height; const char* name; };
  static constexpr Size kSizes[] = {
      {1440, 900, "1440x900"}, {1680, 1050, "1680x1050"},
      {1920, 1200, "1920x1200"}, {2560, 1600, "2560x1600"},
      {3840, 2160, "3840x2160"}, {5120, 2880, "5120x2880"},
      {8192, 4608, "8192x4608"}};
  const char* selected = std::getenv("METABROWSER_DISPLAY_SIZE");
  const std::string_view selection = selected ? selected : "1440x900";
  bool found = false;
  for (const auto& size : kSizes) found |= selection == size.name;
  bool eligible = !found;
  const auto outer = frame.GetChromeClient().RootWindowRect(frame);
  for (const auto& size : kSizes) {
    eligible |= selection == size.name;
    if (eligible && size.width >= outer.width() && size.height - 24 >= outer.height())
      return gfx::Rect(0, 0, size.width, size.height);
  }
  // A legitimate oversized/spanning window cannot exceed its reported display.
  // This depends only on window dimensions already visible to the page, never
  // physical monitor dimensions, IDs, layout, gamut or model labels.
  return gfx::Rect(0, 0, std::max(8192, outer.width()),
                   std::max(4608, outer.height() + 24));
}

// The permission service is browser-authoritative. Quietly observing permission
// never requests a grant. Detailed displays remain available after an actual
// user grant; revocation restores the public virtual display and CSS queries.
class MetaBrowserDisplayPermission final
    : public GarbageCollected<MetaBrowserDisplayPermission>,
      public Supplement<LocalDOMWindow>,
      public mojom::blink::PermissionObserver {
 public:
  inline static constexpr char kSupplementName[] = "MetaBrowserDisplayPermission";
  explicit MetaBrowserDisplayPermission(LocalDOMWindow& window)
      : Supplement<LocalDOMWindow>(window), service_(&window), receiver_(this, &window) {
    window.GetBrowserInterfaceBroker().GetInterface(service_.BindNewPipeAndPassReceiver(
        window.GetTaskRunner(TaskType::kPermission)));
    auto descriptor = mojom::blink::PermissionDescriptor::New();
    descriptor->name = mojom::blink::PermissionName::WINDOW_MANAGEMENT;
    service_->HasPermission(std::move(descriptor),
        BindOnce(&MetaBrowserDisplayPermission::InitialStatus, WrapWeakPersistent(this)));
    if (auto* frame = window.GetFrame()) {
      last_virtual_rect_ = MetaBrowserVirtualDisplay(*frame);
      last_device_scale_ = frame->GetChromeClient().GetScreenInfo(*frame).device_scale_factor;
    }
  }
  static MetaBrowserDisplayPermission* From(LocalDOMWindow& window) {
    auto* state = Supplement<LocalDOMWindow>::From<MetaBrowserDisplayPermission>(window);
    if (!state) {
      state = MakeGarbageCollected<MetaBrowserDisplayPermission>(window);
      Supplement<LocalDOMWindow>::ProvideTo(window, state);
    }
    return state;
  }
  bool allowed() const { return allowed_; }
  uint64_t generation() const { return generation_; }
  bool VirtualScreenChanged(LocalDOMWindow& window) {
    auto* frame = window.GetFrame();
    if (!frame) return false;
    const auto rect = MetaBrowserVirtualDisplay(*frame);
    const float scale = frame->GetChromeClient().GetScreenInfo(*frame).device_scale_factor;
    const bool changed = rect != last_virtual_rect_ || scale != last_device_scale_;
    last_virtual_rect_ = rect;
    last_device_scale_ = scale;
    return changed;
  }
  void InquiryResult(bool granted) {
    has_inquiry_result_ = true;
    Update(granted);
  }
  void OnPermissionStatusChange(mojom::blink::PermissionStatusWithDetailsPtr status) override {
    Update(status->status == mojom::blink::PermissionStatus::GRANTED);
  }
  void Trace(Visitor* visitor) const override {
    visitor->Trace(service_);
    visitor->Trace(receiver_);
    Supplement<LocalDOMWindow>::Trace(visitor);
  }

 private:
  void Update(bool granted) {
    if (allowed_ == granted) return;
    allowed_ = granted;
    ++generation_;
    auto* window = GetSupplementable();
    if (window && !window->IsContextDestroyed() && window->GetFrame())
      window->GetFrame()->MediaQueryAffectingValueChangedForLocalSubtree(MediaValueChange::kOther);
  }
  void InitialStatus(mojom::blink::PermissionStatusWithDetailsPtr status) {
    auto* window = GetSupplementable();
    if (!window || window->IsContextDestroyed()) return;
    // A getScreenDetails result may be newer than this initial quiet inquiry.
    if (!has_inquiry_result_)
      Update(status->status == mojom::blink::PermissionStatus::GRANTED);
    mojo::PendingRemote<mojom::blink::PermissionObserver> observer;
    receiver_.Bind(observer.InitWithNewPipeAndPassReceiver(),
                   window->GetTaskRunner(TaskType::kPermission));
    auto descriptor = mojom::blink::PermissionDescriptor::New();
    descriptor->name = mojom::blink::PermissionName::WINDOW_MANAGEMENT;
    service_->AddPermissionObserver(std::move(descriptor), status.Clone(), std::move(observer));
  }
  gfx::Rect last_virtual_rect_;
  float last_device_scale_ = 1.f;
  uint64_t generation_ = 0;
  bool allowed_ = false;
  bool has_inquiry_result_ = false;
  HeapMojoRemote<mojom::blink::PermissionService> service_;
  HeapMojoReceiver<mojom::blink::PermissionObserver, MetaBrowserDisplayPermission> receiver_;
};

inline bool MetaBrowserDisplayProtected(LocalDOMWindow* window) {
#if BUILDFLAG(IS_MAC)
  const char* display_mode = std::getenv("METABROWSER_DISPLAY_SIZE");
  if (display_mode && std::string_view(display_mode) == "system") return false;
  return window && window->CanvasNoiseToken() &&
      !MetaBrowserDisplayPermission::From(*window)->allowed();
#else
  return false;
#endif
}

// Detailed objects must stop disclosing live metadata after revocation even
// when the user opted into native basic-screen geometry compatibility.
inline bool MetaBrowserDetailedDisplayBlocked(LocalDOMWindow* window) {
#if BUILDFLAG(IS_MAC)
  return window && window->CanvasNoiseToken() &&
      !MetaBrowserDisplayPermission::From(*window)->allowed();
#else
  return false;
#endif
}

inline bool MetaBrowserShouldDispatchScreenChange(LocalDOMWindow& window,
                                                  bool native_changed) {
  if (!MetaBrowserDisplayProtected(&window)) return native_changed;
  return MetaBrowserDisplayPermission::From(window)->VirtualScreenChanged(window);
}

inline void MetaBrowserScreenPermissionInquiry(LocalDOMWindow& window, bool granted) {
  if (window.CanvasNoiseToken())
    MetaBrowserDisplayPermission::From(window)->InquiryResult(granted);
}


}  // namespace blink
#endif
