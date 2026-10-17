#ifndef METABROWSER_DESIGN_TOKENS_H_
#define METABROWSER_DESIGN_TOKENS_H_
#include "third_party/skia/include/core/SkColor.h"
#include "ui/gfx/font_list.h"
#include "ui/gfx/geometry/insets.h"
#include "ui/views/controls/button/md_text_button.h"
#include "ui/views/controls/label.h"
namespace metabrowser::design {
// Metask public UI, sampled 2026-10-15. Neutral surfaces, restrained brand accent.
inline constexpr SkColor kCanvas=SkColorSetRGB(250,250,250);
inline constexpr SkColor kSurface=SK_ColorWHITE;
inline constexpr SkColor kSubtle=SkColorSetRGB(246,246,246);
inline constexpr SkColor kBorder=SkColorSetRGB(230,230,230);
inline constexpr SkColor kInk=SkColorSetRGB(31,31,31);
inline constexpr SkColor kSecondary=SkColorSetRGB(89,89,89);
inline constexpr SkColor kMuted=SkColorSetRGB(118,118,118);
inline constexpr SkColor kAccent=SkColorSetRGB(138,78,209);
inline constexpr SkColor kAccentWash=SkColorSetRGB(243,236,251);
inline gfx::FontList Font(int size,bool bold=false){return gfx::FontList({"SF Pro Text","PingFang SC"},gfx::Font::NORMAL,size,bold?gfx::Font::Weight::MEDIUM:gfx::Font::Weight::NORMAL);}
inline void QuietButton(views::MdTextButton* button){
  button->SetCornerRadius(7);button->SetCustomPadding(gfx::Insets::VH(6,10));
  button->SetMinSize(gfx::Size(0,30));
  button->SetBgColorOverrideDeprecated(SK_ColorTRANSPARENT);
  button->SetStrokeColorOverrideDeprecated(SK_ColorTRANSPARENT);
  button->SetEnabledTextColors(kSecondary);
}
inline void PrimaryButton(views::MdTextButton* button){
  QuietButton(button);button->SetBgColorOverrideDeprecated(kInk);
  button->SetStrokeColorOverrideDeprecated(kInk);button->SetEnabledTextColors(SK_ColorWHITE);
}
}
#endif
