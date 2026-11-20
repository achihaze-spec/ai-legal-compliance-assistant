"""Hazel's AI image / video prompt library, and Asher's prompt picker.

Prompts were collected from TikTok and Facebook (sources kept) and saved here in their
"Optimized for strict consistency" versions. Text in [BRACKETS] is a placeholder: the
picker fills the ones it knows (product, model, setting, voice...) and leaves the rest
for you. `pick()` chooses the right prompts for a product from its category and from
what you have (model photo, product photos, background photo).
"""
from __future__ import annotations

import re

P = []


def _p(id, section, title, text, kind="video", tool="Google Flow", needs=(), source="", note=""):
    P.append({"id": id, "section": section, "title": title, "text": text.strip(), "kind": kind, "tool": tool,
              "needs": list(needs), "source": source, "note": note})


# ───────────────────────── 0. Workflow (master) ─────────────────────────
_p("master", "0. Photos to AI Video workflow", "Master prompt: Shopee Affiliate AI Video Producer", """
Act as my Shopee Affiliate AI Video Producer for the Philippine market.

I will provide downloadable product photos and, when available, product videos from a merchant's listing. I will not record any original footage.
Product: [PRODUCT NAME]. Details from the listing: [PRODUCT DETAILS].

YOUR TASK:
1. Analyze the supplied assets and product information.
2. Create a compelling 30-second vertical affiliate advertisement.
3. Write a natural Taglish voice-over script.
4. Divide the video into 5–6 scenes with suggested durations.
5. Write individual Google Flow prompts for each scene, using the supplied product images as visual references.
6. Specify camera movements, lighting, backgrounds, transitions, and visual effects.
7. Write on-screen captions and a soft-sell CTA.
8. Provide a final CapCut editing sequence.

VISUAL STYLE:
Cozy lifestyle, realistic aesthetic, premium commercial look, natural lighting, smooth camera movement, 9:16 vertical format.

PRODUCT ACCURACY:
- Preserve the product's actual appearance, packaging, color, proportions, and visible branding.
- Use supplied images as references, not as permission to invent product details.
- Do not invent features, discounts, ratings, testimonials, or results.
- Do not generate misleading product demonstrations.
- If a scene risks changing the product's appearance, recommend using the original product image with subtle motion effects instead.

ASSET-ONLY RULE:
Do not request original footage from me. Build the video entirely from available merchant assets, image animation, AI-generated supporting scenes, motion graphics, and editing.

MY POSTING RULES:
- No prices anywhere, no platform names in the script, captions or on-screen text.
- CTA: "check the basket" (never "yellow basket"); add #ad and turn on the AI-generated label.

Return:
A. Product summary
B. Hook options
C. Final voice-over
D. Scene-by-scene storyboard
E. Google Flow prompts
F. On-screen captions
G. CapCut editing instructions
H. Posting caption and CTA
""", kind="text", tool="ChatGPT / Claude / Gemini", needs=["product photos"],
   note="Step 2 (ChatGPT) of the Photos-to-AI-Video workflow. Step 3: Gemini for image analysis, Step 4: Claude for the final Taglish/claims check.")

_p("hybrid", "0. Photos to AI Video workflow", "Hybrid technique (keeps the product exact)", """
Product shot: the original merchant photo with zoom, pan and parallax animation (done in CapCut or by the Video Editor), not an AI clip.
Lifestyle shot: an AI-generated background or scene, using the product photo as a reference only if the tool keeps the label exact.
Final shot: the original product photo again, with the CTA ("check the basket") and the affiliate disclosure (#ad).
Use only merchant assets that are allowed for affiliate promotion: a downloadable photo is not automatically permission to republish it.
""", kind="workflow", tool="CapCut")

# ───────────────────────── 1. Fashion and outfit ─────────────────────────
_p("poses_a", "1. Fashion and Outfit Modeling", "Fast feminine poses (A)", """
Use the uploaded photo as the only reference for the model, the top and the background. Create a vertical 9:16 video of the exact same woman modeling this [ITEM] in 5 quick feminine poses, one after another, in one continuous shot: hand on hip, hair touch, half turn to show the side of the [ITEM], fingers lightly holding the hem, final pose facing the camera. The camera starts at a medium shot and slowly zooms in by the last pose. Keep her face, hair, skin tone, body proportions, the [ITEM] (color, print, fit, neckline, buttons) and the background exactly as in the photo, with the same lighting from start to end. No outfit change, no new objects, no cuts.
Avoid: different face, changed hair, changed top color or print, warped fabric, background change, extra fingers, text, watermark.
""", needs=["model wearing the item"], source="CrispIdentity (Facebook)")

_p("poses_b", "1. Fashion and Outfit Modeling", "Fast feminine poses with eye contact (B)", """
Use the uploaded photo as the only reference for the model, the top and the background. Create a vertical 9:16 video of the exact same woman flexing this [ITEM] in 5 feminine poses with snappy movement, slightly faster than normal, in one continuous shot. She stands close to the camera in a waist-up frame and looks directly into the lens in every pose: hand on hip, hair flip, shoulder turn, hand on the collar or neckline, final confident pose facing the camera. Keep her face, hair, skin tone, the [ITEM] (color, print, fit, neckline, buttons) and the background exactly as in the photo, with the same lighting throughout. No outfit change, no new objects, no cuts.
Avoid: different face, face morphing during fast moves, changed hair, changed top color or print, background change, motion-blurred face, extra fingers, text, watermark.
""", needs=["model wearing the item"], source="CrispIdentity (Facebook)")

_p("colors", "1. Fashion and Outfit Modeling", "10-second color transitions", """
Create a 10-second vertical 9:16 video of the exact woman from image 1 showcasing the same [ITEM] in [NUMBER] colors from images 2 to [N], in this order: [COLOR 1], [COLOR 2], [COLOR 3], [COLOR 4]. Each color lasts about [2.5] seconds and changes with a fast snap transition on the beat. Only the color of the [ITEM] changes: its cut, fit, length, neckline, buttons and print stay identical and match the product photos.
Her face, hair, makeup, accessories, [BOTTOMS] and the background stay exactly the same in every color: [SETTING]. No walking, no speaking. Smooth natural movements only: hair touch, gentle pose change, mirror selfie pose, subtle twirl. Camera: slow push-ins and one macro fabric shot per color, shallow depth of field, realistic fabric physics, natural skin texture, light from the same direction in every shot.
Avoid: different face between colors, hair change, background change, wrong color order, invented colors, changed cut or print, extra fingers, text, watermark.
""", needs=["model photo", "one product photo per color"], source="TikTok")

_p("grwm", "1. Fashion and Outfit Modeling", "GRWM 12-panel storyboard", """
Use image 1 as my exact face and body and image 2 (flat-lay) as the exact outfit: [TOP], [SKIRT], [BAG], [BOOTS]. Create a 12-panel storyboard in a 3 x 4 grid, each panel vertical 9:16, for a get-ready-with-me video in the same room: [ROOM].
Panel 1: me in clean, plain [COLOR] nightwear. Panels 2 to 11: one step per panel, adding one styling step or one outfit piece at a time (skincare, makeup, hair, top, skirt, boots, bag, accessories, mirror check). Panel 12: the full outfit, full body, facing the camera.
Same face, hair length and color, body proportions, room, furniture and window light from the left in all 12 panels. Every outfit piece matches the flat-lay exactly in color, pattern and details. No text or captions in the panels.
Avoid: different person between panels, room changes, outfit pieces not in the flat-lay, changed colors, extra fingers, watermark.
""", kind="image", tool="ChatGPT / Gemini", needs=["model photo", "flat-lay of the full outfit"], source="TikTok")

_p("set_front", "1. Fashion and Outfit Modeling", "Realistic outfit set: universal Front / Full-body view", """
Image 1 ([REFERENCE MODEL IMAGE]) is the only identity reference. Image 2 ([OUTFIT & POSE IMAGE]) is the only outfit and pose reference. Optional image 3 ([APPROVED SHOT]) is the approved first shot of this set: match its face, outfit, setting and light.
A highly realistic, unedited candid full-body photograph, vertical 9:16, of the exact person from image 1: same face shape, eyes, brows, nose, lips, skin tone, [DISTINCTIVE FEATURES WITH SIDE], [HAIR LENGTH, COLOR, TEXTURE AND PART]. Do not beautify, age or replace them.
They stand facing the camera in the exact relaxed pose from image 2, head to toe in frame, wearing the exact outfit from image 2 with every detail unchanged:
- Top: [TOP with color, fabric, collar, closures, details and which side].
- Bottoms: [BOTTOMS with color, fabric, rise, cut, length].
- Shoes/Accessories: [SHOES AND ACCESSORIES and which side].
Setting (copy word for word into every shot of this set): [SETTING], natural daylight from the left, [TIME OF DAY].
Handheld digital camera at eye level, subtle film grain, natural skin texture with pores, flyaway hairs, real fabric folds and creases, realistic depth of field, no studio backdrop, no retouching.
Avoid: different person, changed facial features, missing or moved marks, changed hair, changed outfit color, pattern or details, missing or extra accessories, different setting, light from a different side, plastic skin, extra fingers, text, watermark.
""", kind="image", tool="Gemini / ChatGPT", needs=["model photo", "outfit and pose photo"], source="Gemini reply",
   note="Generate the front view first, approve it, then attach it as image 3 for the other views.")

_p("set_side", "1. Fashion and Outfit Modeling", "Realistic outfit set: universal Side / Profile view", """
Image 1 ([REFERENCE MODEL IMAGE]) is the only identity reference. Image 2 ([OUTFIT & POSE IMAGE]) is the only outfit and pose reference. Optional image 3 ([APPROVED FRONT SHOT]): match its face, outfit, setting and light.
A candid, unedited, handheld-style natural daylight side-profile photograph, vertical 9:16, of the exact person from image 1, framed from the [waist up / knees up / full body], in the exact side-profile pose from image 2. Face in a [sharp profile / three-quarter turn], gaze [looking outward / turned slightly back toward the camera]. Same facial features, skin tone, [MARKS WITH SIDE] and [HAIR LENGTH, COLOR, TEXTURE AND PART], hair falling naturally over the back and shoulders.
They wear the exact outfit from image 2 with every detail unchanged:
- Top: [TOP with color, fabric, details and which side].
- Bottoms: [BOTTOMS with color, fabric, cut].
- Details: [BRACELET, BAG OR SHOES and which side].
Setting (same line as the Front template): [SETTING], natural daylight from the left, [TIME OF DAY], background slightly out of focus.
Realistic handheld camera quality: visible skin texture, subtle flyaway hairs, natural folds and draping in the fabric, soft authentic depth of field, light grain. A real casual snapshot, not a studio photo.
Avoid: different person, changed facial features, missing or moved marks, changed hair, changed outfit details, detail on the wrong side, different setting, light from a different side, plastic skin, extra fingers, text, watermark.
""", kind="image", tool="Gemini / ChatGPT", needs=["model photo", "outfit and pose photo"], source="Gemini reply")

# ───────────────────────── 2. Talking model ─────────────────────────
_p("dress_talk", "2. Talking Model", "Dress promo, model speaks (2 x 8 s, ask the AI to write it)", """
Gumawa ng 2 video prompts (8 seconds bawat isa, vertical 9:16) para sa model sa image 1 na suot ang [ITEM] sa image 1. Siya mismo ang nagsasalita habang nagpo-promote ng suot niyang [ITEM]. Simulan ang bawat prompt sa parehong anchor text, word for word: mukha at marks, buhok, [ITEM] (kulay, tela, haba, neckline, detalye), background at direksyon ng ilaw, at boses ([VOICE]). Prompt 1: hook at unang features ng [ITEM]. Prompt 2: karugtong, nagsisimula sa parehong pose at framing kung saan natapos ang Prompt 1. Ilagay ang eksaktong Tagalog script sa loob ng quotes. Medium shot, single continuous shot, walang cuts. Tapusin ang bawat prompt sa: Avoid: ibang mukha, ibang [ITEM], ibang background, ibang boses, subtitles, text, watermark.
""", kind="text", tool="ChatGPT / Gemini / Claude → Flow", needs=["model wearing the item"])

_p("bestie", "2. Talking Model", "Natural talking model, bestie tone", """
Use the first image as the only reference for her face, hair, outfit, background and lighting. Vertical 9:16, medium shot from the chest up, camera at eye level, static or very slow push-in, single continuous shot.
She talks to the camera naturally and slowly, relaxed breathing, never out of breath, in a friendly bestie tone. Facial expressions and hand gestures follow what she says: subtle inhale before speaking, parted lips, relaxed resting face, slight head tilt, micro-expressions only. Same voice throughout: [VOICE].
Keep her face, hair, makeup, outfit, background and lighting exactly as in the first image for the whole clip. She says: "[SCRIPT]"
Avoid: face change, face zoom, close-ups, cuts, background change, outfit change, exaggerated mouth movement, extra fingers, subtitles, text, watermark.
""", needs=["model photo"], source="sabia_ (TikTok)")

_p("backpack", "2. Talking Model", "Backpack recommendation, 4 scenes (ask the AI to write them)", """
Image 1 is my model, image 2 is the backpack. Write 4 scene-by-scene video prompts (8 seconds each, vertical 9:16) where she recommends this backpack as her back-to-school essential, realistic UGC TikTok style.
Start every scene prompt with the same anchor text, copied word for word: her face, hair, outfit, the backpack (exact color, material, logo, zippers, straps, every compartment) and one fixed setting ([SETTING]).
Scenes: 1 holding the bag up to the camera; 2 wearing it on both shoulders; 3 packing school items into it; 4 opening each compartment and explaining why it is useful for high school students. Each scene has one camera angle, one action and a single continuous shot, with the backpack logo facing the camera.
End every scene prompt with: Avoid: different person, different backpack color or logo, extra or missing pockets, background change, text, watermark.
""", kind="text", tool="ChatGPT / Gemini → Flow", needs=["model photo", "product photo"], source="TikTok")

_p("decor10", "2. Talking Model", "10-second Taglish promo, with face or faceless (decoration)", """
10-SECOND DECORATION VIDEO: MASTER PROMPT. Analyze ALL uploaded reference images first. Automatically determine the best scenes, actions, camera angles, transitions, and dialogue based on the actual decoration. Do not use a fixed storyboard.
PRODUCT LOCK: MAX. Keep the exact same decoration in every scene. Preserve design, shape, size, color, material, texture, pattern, logo, ornaments, and all visible details. No redesign, morphing, duplication, or invented features.
MODEL / IDENTITY LOCK: MAX. If a person is provided, preserve the exact same face, identity, hairstyle, body proportions, outfit, and appearance. No face morphing or identity drift. If none is provided, use a consistent faceless creator.
NARRATOR / VOICE LOCK: If a narrator is provided, preserve the same voice, accent, tone, and speaking style. If none is provided, use one consistent natural Filipino/Tagalog-English creator voice.
DIALOGUE: Create a short, spontaneous-sounding Tagalog-English (Taglish) line based on the actual product. Use a natural Filipino accent, conversational phrasing, and realistic creator delivery. Avoid robotic, overly formal, scripted, or exaggerated dialogue.
BACKGROUND: Use the provided background exactly. If none is provided, create a realistic aesthetic setting that makes the decoration stand out.
VIDEO: 10 seconds, 8 to 10 dynamic scenes, 9:16. Scenes must adapt to the product.
CAMERA: Natural smartphone creator filming. Dynamically use appropriate push-in, pull-back, pan, tilt, tracking, orbit, close-up, wide reveal, or handheld movement.
TRANSITIONS: Use seamless, natural match cuts, movement transitions, object wipes, reframing, whip pans, or push-through transitions when appropriate.
STYLE: Authentic Filipino creator content, realistic lighting, natural movement, believable interaction, subtle handheld imperfections. Not an overly polished commercial.
PRIORITY: EXACT PRODUCT → IDENTITY/VOICE LOCK → NATURAL TAGLISH DIALOGUE → PRODUCT VISIBILITY → CAMERA → SEAMLESS TRANSITIONS → AUTHENTIC CREATOR STYLE.
""", needs=["1-2 product photos"], source="TikTok prompt card")

# ───────────────────────── 3. Selfie / UGC ─────────────────────────
_p("selfie", "3. Realistic Selfie / UGC", "Selfie master prompt (image)", """
Use image 1 as the exact identity reference and image 2 as the exact outfit reference. Optional image 3: background reference.
A raw, unedited selfie-style photograph, vertical 9:16, of [MODEL NAME], the exact person in image 1: [KEY PHYSICAL TRAITS: face, marks with side, hair length, color and part]. Do not beautify, age or replace them. They hold a smartphone in front of a [MIRROR / REFLECTIVE SURFACE] in [SETTING], wearing the exact outfit from image 2: [OUTFIT with colors, fabric, prints], with natural draping, visible wrinkles and realistic bunching.
Expression: [EXPRESSION], relaxed and natural. Hair and small details slightly imperfect and unstyled. The phone covers only the [lower left / lower right] corner of the face; both eyes stay visible. Framing slightly off-center and uneven, as if casually taken.
Lighting: soft single-direction light from a window on the left, diffused shadows, low contrast. Colors muted, slightly dull and desaturated. Smartphone look: slight motion blur, subtle grain, minor exposure inconsistencies, natural matte skin texture with no glow or smoothing. The subject dominates the frame; the background stays soft and secondary.
Avoid: different face, changed hair or outfit, face fully hidden by the phone, plastic skin, beauty filter, symmetrical studio framing, vibrant colors, extra fingers, text, watermark.
""", kind="image", tool="Gemini / ChatGPT", needs=["model photo", "outfit photo"])

_p("selfie_anim", "3. Realistic Selfie / UGC", "Animate the selfie (video)", """
Animate this image into a realistic handheld selfie video, vertical 9:16, [5 to 8] seconds, single continuous shot. Treat the image as the first frame and the only reference: face, hair, outfit, phone position, lighting, background and framing stay exactly the same from the first to the last frame.
Movement only: slight head tilt or micro turn (small, under 15 degrees), natural blinking, small eye shifts, gentle breathing, tiny posture adjustments. Camera: slight handheld phone shake, minor motion blur, soft focus breathing, small exposure changes. The phone keeps covering the same part of the face. Keep the natural skin texture, original grain and muted colors.
Avoid: face morphing, identity drift, hair or outfit change, new objects, background change, big head turns, cuts, cinematic color grade, smoothing, sharpening, text, watermark.
""", needs=["approved selfie still"])

_p("photo2json", "3. Realistic Selfie / UGC", "Convert a photo into a JSON prompt", """
Analyze this photo and convert it into a detailed JSON prompt for photorealistic image generation. Use these keys: prompt_type, character_id, reference_images, aspect_ratio, subject (description, hair, face, expression, accessories, outfit), pose (type, camera_tilt, framing, eye_contact, what each hand is doing), environment (3 to 6 fixed objects with their positions), lighting (type, direction, time_of_day, mood), camera (device, lens, angle, depth_of_field), style (realism, color_grade, quality), consistency_lock, negative_prompt. Describe only what is visible; write "not visible" instead of guessing. Write left and right from the viewer's side and say so. Be specific about colors, textures, prints and logos, hair part, beauty marks and their side. consistency_lock lists the features that must never change. Output valid JSON only.
""", kind="text", tool="Claude / ChatGPT / Gemini", needs=["reference photo"])

_p("kitchen", "3. Realistic Selfie / UGC", "Night kitchen, harsh flash (camera briefing)", """
Vertical 9:16 phone video at night, harsh direct on-camera flash, slightly grainy, single continuous handheld shot. Character [ID, e.g. Ken-V1]: Asian man in his [40s], short black hair, creased grey crew-neck t-shirt (attach his photo as image 1 if you have one; keep him identical). Set, identical in every clip: small cluttered home kitchen, sauce bottles with drips on the left counter, rice cooker with a scratched lid beside them, damp tea towel over the oven handle, one cabinet door ajar above the stove. He stir-fries vegetables in a black wok; steam catches the flash; he steps back once as oil pops. Imperfect framing, sometimes cut off at the elbow.
Avoid: different man, clean showroom kitchen, moved or missing props, soft studio lighting, text, watermark.
""", source="Roy Tan (TikTok)")

_p("hawker", "3. Realistic Selfie / UGC", "Hawker stall at golden hour (camera briefing)", """
Vertical 9:16 phone video at golden hour, shot into the sun from the left, lens flare and a smudge on the lens, slightly grainy, colours a bit blown where the sun hits. Set, identical in every clip: hawker stall at dusk, steam rising off a wok, red plastic stools, a standing fan turning, laminated menus curling at the corners. Character [ID, e.g. Uncle-Lim-V1]: older uncle in a white singlet, [grey crew cut], counting coins at the counter. Handheld walk-past, focus hunts once then locks. Feels like a clip from someone's camera roll.
Avoid: different uncle, different stall layout, clean modern food court, sun from the other side, text, watermark.
""", source="Roy Tan (TikTok)")

_p("laugh", "3. Realistic Selfie / UGC", "Candid laugh by the window (camera briefing)", """
Vertical 9:16 phone video, indoors by a window on the left of a living room, uneven light, the left half of her face brighter than the right. Character [MODEL NAME]: Asian woman in her thirties, [hair length, color, part], [top] (attach her photo as image 1 if you have one; keep her identical). She laughs mid-conversation and looks slightly past the camera, flyaway hairs, slight motion blur as she turns her head, visible skin texture. Set, identical in every clip: cluttered wooden bookshelf soft behind her on the right, [one more fixed object]. Feels like a candid clip a friend took. A little camera shake, single continuous shot.
Avoid: different woman, window on the other side, different room, glossy skin, text, watermark.
""", needs=["model photo"], source="Roy Tan (TikTok)")

# ───────────────────────── 4. Faceless product ─────────────────────────
_p("faceless", "4. Faceless Product Shots", "Faceless marketing video (any product)", """
Use the uploaded photo as the only product reference. Analyze the product first: shape, size, color, material, logo, label text and cap or closure. Create a vertical 9:16 faceless product video, [8] seconds, single continuous shot, slow camera push-in. Setting: [AESTHETIC BACKGROUND]. Show only the product, one hand and, if needed, lips in the lower part of the frame; no full face. The product keeps its exact shape, colors, logo and label text in every frame, label facing the camera. No text, no voice-over.
Avoid: redesigned product, changed or misspelled label, extra products, full face, extra fingers, background change, text overlay, watermark.
""", needs=["product photo"])

_p("fiveshot", "4. Faceless Product Shots", "5-shot product sequence", """
Anchor for all 5 shots (paste before each shot): Image 1 is the exact product: preserve its shape, size, color, material, logo and label text, label facing the camera. Set: [TABLE AND BACKGROUND]. One woman's hand: [HAND DETAIL]. Vertical 9:16, single continuous shot per clip, slow smooth motion.
1. [ANCHOR] + Slight blur intro: camera slowly focuses while pushing in toward the product on the table.
2. [ANCHOR] + Side angle: the same hand gently places the product on the table.
3. [ANCHOR] + Close-up angle: fingers softly glide over the product surface; the label stays readable.
4. [ANCHOR] + Top-diagonal angle: one finger lightly taps the product (satisfying motion).
5. [ANCHOR] + Front close-up: the hand lifts and slightly rotates the product, ending with the label facing the camera.
Avoid (end of every shot): changed product shape or color, misspelled or melted label, second product, two different hands, different table or light, text, watermark.
""", needs=["product photo"], source="Carla (TikTok)")

_p("serum_pov", "4. Faceless Product Shots", "Serum POV (short)", """
POV serum review, vertical 9:16, single continuous shot. Image 1 is the exact serum bottle: keep its shape, glass color, dropper cap, label design and every printed word exactly as shown, readable and facing the camera. Focus on the bottle only, on [SETTING]. Avoid: changed or misspelled text, redesigned bottle, extra bottles, background change, text overlay.
""", needs=["product photo"])

_p("serum_drip", "4. Faceless Product Shots", "Serum hand pick-up and drip", """
Image 1 is the exact serum bottle. Analyze it first and preserve its shape, glass color, dropper, label and all printed text. Vertical 9:16, single continuous shot, [SETTING].
A woman's hand ([HAND DETAIL]) slowly enters the frame, gently picks up the bottle and slowly rotates it so the label is clearly visible. The camera slowly and smoothly zooms in toward the bottle. The same hand opens the dropper, slowly lifts it and lets the serum drip back into the bottle. The bottle and every word on it stay exactly the same in every frame.
Avoid: changed or misspelled label, redesigned bottle, second hand, extra fingers, background change, text overlay, watermark.
""", needs=["product photo"])

_p("skincare_pov", "4. Faceless Product Shots", "Skincare routine POV (one hand, continuous shot)", """
Image 1 is the exact serum bottle; image 2 is the background. Analyze the bottle first and preserve its shape, glass color, cap, dropper, label and all printed text. Create a realistic skincare routine POV video, vertical 9:16, in one continuous scene with no cuts, using the exact background from image 2. Static camera; the background does not move.
Only one human hand ([HAND DETAIL]) is visible for the whole video. The bottle stands on the table, label facing the camera, clearly visible from start to finish. The hand enters, holds the bottle, slowly opens the cap, lifts the dropper, points it at its own palm and slowly drops serum onto the palm. The palm tilts toward the camera to show the serum texture, while the bottle stays on the table in the background, unchanged.
Avoid: second hand, extra fingers, changed or misspelled label, bottle moving on its own, background movement, cuts, text, watermark.
""", needs=["product photo", "background photo"])

_p("infographic", "4. Faceless Product Shots", "UGC infographic storyboard image (6 scenes, no face)", """
Create a highly detailed premium UGC infographic storyboard image for this product using the exact uploaded images. 6 scenes, 10 seconds, aspect ratio 9:16. The first image and second as the product and the third image as the background. Show scene-by-scene camera angles, model actions (no face shown), lighting, background, transitions, product close-ups, and premium TikTok Shop ad style. Keep the product exactly the same.
""", kind="image", tool="ChatGPT / Gemini", needs=["2 product photos", "background photo"], source="TikTok")

_p("story2video", "4. Faceless Product Shots", "Storyboard to video (step 2)", """
Create a high quality video based on the first image as the storyboard, the second image as the exact look of the product, the third image as the background of the video, don't add text or captions on the video, no talking or backtrack, don't change the background and don't change the product look.
""", needs=["storyboard image", "product photo", "background photo"], source="TikTok")

# ───────────────────────── 5. Perfume ─────────────────────────
PERFUME_ANCHOR = ("Image 1 is the exact perfume bottle. Analyze it first and preserve its exact design, shape, proportions, glass color and texture, "
                  "cap, logo, label and printed text. Do not redesign, restyle or add parts. Keep the label facing the camera and readable. "
                  "Set palette for the whole series: soft pastel pink and lavender, white marble, soft diffused light from the left. "
                  "Vertical 9:16, 4 seconds, single continuous shot, ultra-photorealistic.")
PERFUME_AVOID = ("Avoid: changed bottle shape, changed cap, misspelled or melted label, logo change, extra bottles, color shift, "
                 "light from a different side, text overlay, watermark.")
_p("perfume1", "5. Perfume Cinematic Set", "Perfume 1: Hero reveal", PERFUME_ANCHOR + """
The bottle stands centered on a glossy white marble surface with a soft pastel pink and lavender gradient background and elegant reflections. The camera starts at a 45-degree front hero angle and performs a slow cinematic push-in toward the bottle. Luxury perfume commercial.
""" + PERFUME_AVOID, needs=["product photo"], source="aLysa.digital")
_p("perfume2", "5. Perfume Cinematic Set", "Perfume 2: Luxury detail", PERFUME_ANCHOR + """
Extreme macro close-up of [GLASS DETAIL], [CAP] and the logo. The camera slowly slides from left to right while soft highlights shimmer across the glass. The logo and label stay sharp and correctly spelled throughout. Premium beauty commercial.
""" + PERFUME_AVOID, needs=["product photo"], source="aLysa.digital")
_p("perfume3", "5. Perfume Cinematic Set", "Perfume 3: Elegant orbit", PERFUME_ANCHOR + """
The bottle stands on a reflective acrylic platform with a pastel pink and lavender floral background. The camera performs a smooth, slow 180-degree orbit around the bottle, starting and ending with the label facing the camera, logo and text sharp and unchanged at every angle. Luxury commercial.
""" + PERFUME_AVOID, needs=["product photo"], source="aLysa.digital")
_p("perfume5", "5. Perfume Cinematic Set", "Perfume 5: Floral story", PERFUME_ANCHOR + """
Peony petals, rose petals, lavender sprigs, lemon slices, pearls and white silk fabric are arranged around the bottle on white marble, none covering the bottle or label. The camera starts directly overhead and gently pushes toward the center. Soft natural light from the left. Premium beauty commercial.
""" + PERFUME_AVOID, needs=["product photo"], source="aLysa.digital")
_p("perfume6", "5. Perfume Cinematic Set", "Perfume 6: Try-on test (with model)", PERFUME_ANCHOR + """
Image 2 is the exact model [MODEL NAME]: same face, skin tone, marks, hair length, color and part. Do not beautify or replace her. If the bottle has a cap, she naturally removes it first; if it has none, do not add one.
She wears a white satin [TOP/DRESS] and stands in a luxurious vanity room: [3 FIXED DETAILS, e.g. round mirror with warm bulbs, white vanity table, pink roses], soft natural light from the left. She gracefully picks up the perfume, sprays once on her neck and once on her wrist, then gently smells her wrist with a confident smile while holding the bottle with the label facing the camera.
Medium shot at eye level, smooth slow push-in, single continuous shot, realistic hand movements, shallow depth of field, 9:16.
Avoid: different face, identity drift, bottle deformation, label change, cap added or changed, extra fingers, outfit change, cuts, text, watermark.
""", needs=["product photo", "model photo"], source="aLysa.digital")

# ───────────────────────── 6. Hacks and hooks ─────────────────────────
_p("commercial", "6. Quick Hacks and Hooks", "Google Flow one-word hack", """
Type \\Commercial, then add: Keep the product exactly as in the reference image: same shape, colors, logo and label text, label facing the camera. One setting, one light direction, single continuous shot, vertical 9:16. No text, no watermark.
""", needs=["product photo"], source="marlex (TikTok)")
_p("slash", "6. Quick Hacks and Hooks", "Simple slash commands", """
[COMMAND: /UGC ad, /cinematic ad, /luxury ad, /unboxing ad, /viral commercial, /smoke reveal or /POV product demo] + Keep the product exactly as in the uploaded photo: same shape, colors, logo and label text, label readable. If a model is attached, keep her exact face, hair and outfit. One setting and one light direction, single continuous shot, vertical 9:16. No text, no watermark.
""", needs=["product photo"], source="Facebook post")
_p("hooks", "6. Quick Hacks and Hooks", "Intro hook ideas", """
Hook types: text reveal, problem-solution, countdown, mystery, before/after (only if the listing supports it), question hook, sound effect, behind-the-scenes, controversial statement, or direct address. Mix with actions like a wink, finger heart, or eye contact.
Hook prompt: [ANCHOR TEXT] + [HOOK, e.g. question hook, she leans into the lens] + [ACTION, e.g. wink, finger heart, direct eye contact]. Single continuous shot, vertical 9:16. Shoot the hook with the same model, outfit and setting as the rest of the video.
""", kind="text", source="TikTok Tako AI")
_p("bag", "6. Quick Hacks and Hooks", "6-second bag montage hook", """
Analyze the uploaded bag reference FIRST: identify its type, design, material, intended use, strongest feature, and visual personality. Create a 6-second, 9:16 fast-paced cinematic hook montage with 2 to 3 scenes, choosing an unexpected hook that naturally fits the bag.
Start with an unpredictable visual hook such as throw-in, drop-in, side pop, sudden reveal, snap transformation, floating reveal, cinematic whip reveal, gravity-defying placement, environmental interaction, or FOMO "wait, what?" moment. Let the reference determine the hook and scene flow.
Create an instant emotional reaction (surprise, curiosity, excitement, desire, or satisfaction), then transition smoothly into a final premium HERO SHOT of the bag.
PRODUCT LOCK: MAX. Preserve exact shape, proportions, color, material, texture, stitching, straps, hardware, zipper, logo, pattern, and every recognizable detail. No redesign, morphing, distortion, or invented features.
MODEL RULE: If a model is provided, use the exact person with strict IDENTITY/FACE + OUTFIT LOCK. If no model is provided, DO NOT ADD ANY PERSON, HANDS, BODY, SILHOUETTE, OR HUMAN ELEMENTS. PRODUCT ONLY.
Image roles: image 1 is the bag (PRODUCT LOCK: MAX). Image 2, if attached, is the model (IDENTITY/FACE + OUTFIT LOCK). Keep one environment and one light direction in all scenes: [ENVIRONMENT, e.g. sunlit concrete rooftop, light from the left]. Hero shot: same angle as the reference photo, logo facing the camera, full bag in frame.
Fast cinematic movement, seamless transitions, realistic physics, dramatic but natural environmental effects, premium photorealism, realistic lighting and motion blur.
FINAL SCENE: Clean, striking hero shot. Bag fully visible, perfectly composed, visually dominant, sharp and premium.
No unnecessary dialogue, text, or generic product showcase. The first frame must stop the scroll; the final frame must make the product memorable.
Avoid: bag color shift between scenes, changed hardware or logo, extra straps or pockets, second bag, person added when no model is attached, text, watermark.
""", needs=["product photo"], source="@angelicalysa (TikTok)")
_p("episodes", "6. Quick Hacks and Hooks", "Character consistency across episodes", """
[MODEL NAME] is the exact person in the attached reference image. In every episode use the same reference image and this descriptor word for word: [DESCRIPTOR: age, ethnicity, face, marks with side, hair length, color and part, build, outfit with colors]. Never change their face, facial marks, hairstyle, hair color, body proportions, clothing colors, voice ([VOICE]) or personality. Home set, unless the episode says otherwise: [SETTING].
Avoid: different person, identity drift, outfit color change, different voice, different home set.
""", needs=["model photo"], note="Tip: generate drafts in 360p to save credits.")

# ───────────────────────── 7. Model swap ─────────────────────────
_p("swap1", "7. Model Swap Workflow", "Step 1: image prompt (ChatGPT)", """
Image 1 is the pose and background reference (Pinterest photo). Image 2 is the exact product (TikTok Shop screenshot). Image 3 is my face, the identity reference. Create a new photorealistic photo, vertical 9:16. Keep the pose, framing and camera angle of image 1. Replace the person with the exact woman from image 3: same face shape, eyes, nose, lips, skin tone, marks and [HAIR]. Dress her in the exact [PRODUCT NAME] from image 2: same color, fabric, cut, length, print and details. Background: similar to image 1, [3 TO 4 ELEMENTS]. Natural skin texture, real fabric wrinkles, smartphone photo look.
Avoid: the face from image 1, changed product color or details, prices, buttons or text from the screenshot, extra fingers, watermark.
""", kind="image", tool="ChatGPT", needs=["pose photo (Pinterest 'outfit check')", "product screenshot", "your face selfie"], source="TikTok tutorial")
_p("swap2", "7. Model Swap Workflow", "Step 2: ask for the image-to-video prompt", """
Give me an image-to-video prompt for Google Flow, using the image I generated as the first frame, vertical 9:16, with a voiceover hook selling [PRODUCT NAME]. Focus only on movement, camera angle and posing. Change the pose or camera every 4 seconds, but keep the same person, [ITEM], top, background and light in every part. Start the prompt with an anchor describing her face, hair, outfit and background. End it with: Avoid: different face, changed [ITEM] color or fit, background change, location change, text, watermark.
""", kind="text", tool="ChatGPT → Flow", needs=["swap image from step 1"])

# ───────────────────────── 8. Character sheet ─────────────────────────
_p("sheet", "8. Character Reference Sheet", "8-panel character sheet", """
Image 1 is the exact person: copy the face, marks, hair and body from it. Photorealistic character reference sheet for [MODEL NAME], vertical 2:3, seamless white studio background, 8-panel grid with thin white dividers. The same person in every panel, with identical face, hair, outfit, skin tone and proportions, lit the same way.
Row 1, full body (4 panels): front view with hands in pockets, left side profile, back view, three-quarter back view looking over the shoulder.
Rows 2 and 3, close-ups from the shoulders up (4 panels): three-quarter face looking at the camera, side profile, back of the head showing the hair, over-the-shoulder face view.
CHARACTER: [MODEL NAME], [ETHNICITY] [GENDER], [AGE]. Hair: [length, color, texture, part]. Eyes: [color, shape]. Brows and lips: [description]. Skin: [tone, marks with side]. Build: [height, body type].
OUTFIT: [TOP], [BOTTOMS], [SHOES]. Accessories: [EARRINGS, NECKLACE, etc., with side].
STYLE: soft even studio light from the front left in every panel, sharp focus, realistic skin texture and fabric detail, natural proportions, the same neutral calm expression in every face panel.
RULES: no text, no labels, no watermarks, no props, no other people, no background elements. Avoid: face changes between panels, marks on different sides, different hair length, outfit changes.
""", kind="image", tool="Gemini / ChatGPT", needs=["model photo"], note="Use the sheet as the reference image in Flow so the face stays the same in every scene.")

# ───────────────────────── 9. Reference-locked affiliate video ─────────────────────────
_p("reflock", "9. Reference-Locked Affiliate Video", "Master template + 3 scenes (person in Veo, real product added in CapCut)", """
Settings: 15 seconds, vertical 9:16, 1080 x 1920, photorealistic cozy lifestyle, premium commercial cinematography. No audio: no music, dialogue, voice-over, or sound effects. Three consecutive 5-second scenes.
Character identity lock: Use the supplied real-person reference photo as the authoritative identity reference. The person must remain the same individual throughout the entire video. Preserve the person's recognizable facial features, face shape, eyes, nose, lips, skin tone, hairstyle, hair color, age appearance, body proportions, and any visible identifying characteristics. Do not beautify, reinterpret, stylize, age, de-age, or replace the person. No facial morphing or identity drift. Use the same reference image for every scene. Prefer simple, natural movements and medium shots.
Wardrobe and setting lock: She wears [OUTFIT] in all three scenes. Setting for all three scenes: [SETTING], natural window light from the left, same time of day.
Overlay area lock: keep the [RIGHT THIRD OF THE FRAME / COFFEE TABLE SURFACE] empty and clean in every scene, in the same place, for the product layer added in editing.
Product rule: Do not recreate, redraw, or regenerate the product. The actual product will be inserted as an original, unaltered layer during editing.
Visual direction: realistic, cozy lifestyle commercial with natural window light, believable shadows, realistic skin texture, warm inviting palette. Reserve clean negative space for a CTA. Do not generate captions, logos, brand names, product labels, watermarks, or promotional text. No audio.

Scene 1 (0-5 s, hook): Use the supplied real-person reference photo to preserve the exact same identity. Show the person in [SETTING], wearing [OUTFIT], performing [SIMPLE ACTION]. Photorealistic skin, stable facial features, gentle camera push-in. Keep the overlay area empty. Do not generate any product, packaging, logo or text. Vertical 9:16. No audio.
Scene 2 (5-10 s, lifestyle): Continue with the exact same person, facial identity, hairstyle, [OUTFIT] and [SETTING], same light direction. Show [SIMPLE LIFESTYLE ACTION] with realistic body movement. Medium close-up, stable camera. Do not simulate interaction with an absent product. Keep the overlay area empty and clean. Vertical 9:16. No audio.
Scene 3 (10-15 s, hero ending): Show the same referenced person in [SETTING], wearing [OUTFIT]. Subtle closing gesture, stable final composition, same light direction. Keep the overlay area empty, and leave the bottom fifth of the frame clear for the CTA. Do not generate a product, packaging, logo or text. Vertical 9:16. No audio.

Negative: Different person, identity drift, face morphing, facial feature changes, skin tone changes, hairstyle changes, wardrobe changes, duplicate person, unnatural hands, extra fingers, flickering face, generated product, fake packaging, invented brand, altered logo, incorrect label, misspelled product text, generated promotional text, watermark, inconsistent lighting, audio, music, dialogue, voice-over, different room, moved furniture, changed light direction, objects in the overlay area.
""", needs=["model photo", "original product photo (for CapCut)"], note="Best when the label keeps changing in AI clips.")

# ───────────────────────── 10. Fashion try-on display ─────────────────────────
_p("tryon", "10. Fashion Try-On Display", "Try-on display: anchor + 2 scenes (stills, then animate)", """
Upload 4 references in this order: 1 model front photo, 2 product (top), 3 pairing item (bottoms), 4 background photo.

ANCHOR (paste unchanged in every scene):
Use image 1 as the exact model [MODEL NAME]: same face, skin tone, [MARKS WITH SIDE], [HAIR LENGTH, COLOR, TEXTURE AND PART]. Do not change her face or hair.
She wears the exact [ITEM] from image 2: [cut, length, sleeves, base color], [print text and logo with colors and placement], [button color], [pocket fabric and placement], [collar]. Preserve the exact print, text, colors and pocket.
She also wears the exact [PAIRING ITEM] from image 3: [color, rise, pleats, cut, length], with the top [untucked/tucked]. [SHOES].
Setting is the exact room from image 4: [SETTING]. (No background photo: "Plain warm off-white wall, soft natural daylight from the left.")
Shot on an iPhone, natural window daylight from the left, true-to-life skin texture with visible pores, real fabric wrinkles and creases, slight natural film grain, realistic depth of field, candid lifestyle photo, not glossy or retouched. Same time of day in every scene: late morning. Write left and right from the viewer's side.

Scene 1, full body (image): [ANCHOR] + Vertical 9:16 full-body shot, camera at chest height, model [MODEL NAME] standing [in front of key background spot], facing the camera, arms relaxed, soft natural expression, the full outfit and print visible. + [IMAGE NEGATIVE]
Scene 1, animate (Frames to Video): [AMBIENT MOTION, e.g. a soft breeze gently moves the sheer curtains; nothing else moves.] Model shifts her weight slightly, turns a little (under 20 degrees) to the left, then back to the camera. [PAIRING ITEM] sways softly. Slow push-in. Single continuous shot, 9:16. Keep the face, print, pocket, colors and the room unchanged from the first frame. + [VIDEO NEGATIVE]
Scene 2, waist-up detail (image, attach the approved Scene 1 still as image 5): [ANCHOR] + Match the face, outfit, colors and room of image 5 exactly. Vertical 9:16 waist-up shot, beside [BACKGROUND ELEMENT], angled three-quarters to the right, one hand lightly resting near the [POCKET/DETAIL], print fully visible and correctly spelled. + [IMAGE NEGATIVE]
Scene 2, animate: [AMBIENT MOTION]. Model slowly turns from three-quarter to front and smooths the hem. Very slow camera drift upward from the hem to the collar. Single continuous shot, 9:16. Keep the face, print, pocket and room unchanged. + [VIDEO NEGATIVE]

IMAGE NEGATIVE: Avoid: different face, changed facial features, missing or moved marks, misspelled text, garbled print, wrong or missing pocket, different [PAIRING ITEM] color, extra fingers, deformed hands, different room, changed furniture, other people, AI look, CGI, plastic or airbrushed skin, oversaturated colors, cartoon, watermark, text overlay, different time of day, different light direction.
VIDEO NEGATIVE: Avoid: face morphing, hair changing, print warping, text melting, pocket disappearing, color shifting, outfit change, curtains flapping wildly, furniture moving, flickering, jittery motion, sudden cuts, scene change, fast zoom, extra hands, warped fingers, other people, subtitles, watermark, identity drift, light direction changing, camera cut.
Checks before animating: face and marks match; print text spelled correctly and logo intact; pocket and buttons correct; pairing item stands out from the background. If text warps in the video, keep the camera static; if the print is still wrong after 2 tries, overlay the real product photo in CapCut.
""", kind="video", tool="Google Flow / Gemini", needs=["model photo", "product photo", "pairing item photo", "background photo (optional)"], source="own workflow (Pablo)")

# ───────────────────────── 11. Consistency workflow ─────────────────────────
_p("c0", "11. Model and Product Consistency", "Prompt 0: image roles", """
Image 1 is the exact identity of [MODEL NAME]. Image 2 is the exact product. Image 3 is the exact setting. Use each image only for its role.
""", kind="text", tool="any")
_p("c1", "11. Model and Product Consistency", "Prompt 1: anchor template", """
[CAMERA / SHOT TYPE] of model [MODEL NAME], [age] [ethnicity] woman, [face features], [hair length, color, texture and part], [beauty marks and which side], wearing [exact outfit with colors, fabric and prints], [shoes and accessories], in [SETTING], soft natural light from the left, [time of day], [ACTION]. Vertical 9:16.
""", kind="text", tool="any")
_p("c2", "11. Model and Product Consistency", "Prompt 2: character lock", """
Use the attached photo as the exact identity of [MODEL NAME]. Keep the same face shape, eyes, nose, lips, skin tone, freckles, beauty marks, hairstyle, hair color and body proportions in every frame. Do not beautify, age, de-age or replace her. No identity drift or face morphing.
""", kind="text", tool="any", needs=["model photo"])
_p("c3a", "11. Model and Product Consistency", "Prompt 3A: product lock", """
Analyze the attached product first. Preserve its exact design, shape, size, proportions, color, logo, label, printed text and material. Do not redraw, restyle or invent any part of the product. Keep the label facing the camera and readable; do not rotate the product more than 30 degrees away from the label.
""", kind="text", tool="any", needs=["product photo"])
_p("c3b", "11. Model and Product Consistency", "Prompt 3B: CapCut overlay (when the label keeps changing)", """
Do not show any product. Leave the [hands / table area / right third of the frame] empty and clean so the real product can be added in editing. No packaging, logos or text.
""", kind="text", tool="any")
_p("c4", "11. Model and Product Consistency", "Prompt 4: still image", """
[PROMPT 1] + [PROMPT 2] + [PROMPT 3A or 3B]. Generate a single photorealistic still image, vertical 9:16, shot on a smartphone, natural skin texture with visible pores, real fabric wrinkles, slight film grain, not glossy or retouched.
""", kind="image", tool="Flow image mode / Gemini")
_p("c5", "11. Model and Product Consistency", "Prompt 5: animate the approved still", """
Animate this image. Keep everything exactly as shown: face, hair, outfit, product, label and background. Movement only: [ACTION, e.g. subtle breathing, natural blinking, she slowly lifts the product toward the camera]. Camera: [slow push-in / static / gentle pan]. Single continuous shot, vertical 9:16, no cuts, no new objects. Keep everything in the first frame unchanged; only the action moves.
""", needs=["approved still"])
_p("c6", "11. Model and Product Consistency", "Prompt 6: negative (every still and clip)", """
Avoid: different person, identity drift, face morphing, marks on the wrong side, changed hair or outfit, beauty filter, plastic skin, extra fingers, deformed hands, altered logo, misspelled label, redrawn or distorted product, duplicate product, different room, moved furniture, changed light direction, camera cuts, flicker, text overlay, watermark.
""", kind="text", tool="any")
_p("c7", "11. Model and Product Consistency", "Prompt 7: fix one detail", """
Same image as before. Change nothing except: [the one detail to fix, e.g. the mole is on the left side of her chin / the label reads correctly]. Keep everything else identical.
""", kind="text", tool="any")
_p("c8", "11. Model and Product Consistency", "Prompt 8: next scene continuity", """
Continue from the attached last frame of the previous clip. Same person, outfit, product, setting and light direction. Only the camera changes to [NEW CAMERA] and the action to [NEW ACTION].
""", needs=["last frame of the previous clip"])

# ───────────────────────── Posting ─────────────────────────
_p("fbreels", "Posting", "FB Reels description (Taglish)", """
[Hook line] 🤍💗
[PRODUCT NAME]. [Material or origin in one line].
✔️ [feature 1]
✔️ [feature 2]
✔️ [feature 3]
✔️ [size note]
🛒 Link sa comments
[3 to 4 hashtags] #ad #aigenerated
(Put the shop link in the first comment, not the caption. No price: prices change, so it is left out on purpose.)
""", kind="text", tool="Facebook", note="Your template had '₱[price] lang!': removed because of your no-price rule.")
_p("hashtags", "Posting", "Hashtags and platform tweaks", """
TikTok: 5 to 6 tags, turn on the AI-generated label. IG Reels: 8 to 10 tags, turn on the AI info label. FB Reels: 3 to 5 tags, link in the first comment. YouTube Shorts: title with #shorts, 3 tags, mark as altered or synthetic content.
Fixed core set on every post: #ad #aigenerated + your brand tag; rotate only the 2 to 3 product-angle tags.
""", kind="text", tool="all platforms")
_p("capcut", "Posting", "CapCut steps", """
1. New project, canvas 9:16, import the clips in scene order.
2. Trim each clip: cut warped frames at the start or end, keep the cleanest 2 to 4 seconds.
3. Product overlay (if you used Prompt 3B): add the real product photo with Overlay, Remove background, place it in the empty area, keyframe it to follow the hand or camera.
4. Apply one Filter / Adjust setting to all clips so skin tone and color match.
5. Add the voiceover or sound, a text hook in the first 2 seconds, auto captions and the CTA ("check the basket") at the end.
6. Export 1080p, 30 fps. Post with the AI-generated label and #ad.
""", kind="workflow", tool="CapCut")

# ───────────────────────── 12-15. Other tools ─────────────────────────
_p("recreate", "15. Video Recreation (Seedance)", "Recreate a viral video's structure", """
Watch this video frame by frame. Then write a prompt for Seedance 2.5 that recreates it as closely as possible, vertical 9:16, same length. Break it into shots with timestamps; for each shot give the camera angle and movement, the action, the lighting direction and any on-screen product. Start the prompt with one anchor paragraph that describes the main character (face, marks with side, hair length, color and part, outfit with colors), the setting (3 to 5 fixed details) and the product (exact shape, colors, logo and label text), and repeat that anchor word for word in every shot. Do not add text, captions or watermarks.
Optional (photo attached): Image 1 is me, the only identity reference. Replace the character in the video with the exact person in image 1. Keep the original pose, movement, outfit and setting unless I say otherwise. Do not beautify, age or replace me.
Avoid: different person between shots, identity drift, face morphing, outfit change, background change, changed product label or logo, extra fingers, text, watermark.
""", kind="text", tool="Claude / ChatGPT / Gemini → Seedance", needs=["the reference video"], note="Use it to learn the structure of a viral video; don't copy someone else's video or music.")
_p("shorts", "12. Long Video to Shorts", "Long video → 7 Shorts (3 prompts, same chat)", """
Prompt 1: Analyze this uploaded video for [AUDIENCE], who struggle with [SPECIFIC PROBLEM]. My content niche is [NICHE], and my goal is [SAVES/FOLLOWS/LEADS]. Return one table with exactly these columns: ID (M01, M02, ...), start (HH:MM:SS), end (HH:MM:SS), topic, takeaway, demonstration or quote (verbatim), audio quality. Flag unclear audio and sections you cannot access. Do not invent dialogue or describe visuals you have not verified.
Prompt 2: Using the video map, identify up to 12 moments that could become [30 to 45]-second Shorts for [PLATFORM]. Each must deliver one understandable takeaway without the full video. Return one table: clip ID (C01...), source map ID, start, end, exact opening words, exact closing words, payoff, missing context, rank. Return fewer if the footage does not support 12 strong clips.
Prompt 3: Select seven candidates for a week of content aimed at [AUDIENCE], each with a different main takeaway. Return one table: day (1 to 7), clip ID, working title, viewer problem, takeaway, reason for selection, overlap flag. If there are not seven strong ideas, name the gap and suggest a specific pickup recording.
""", kind="text", tool="ChatGPT / Claude / Gemini", needs=["a long video"])
_p("youtube", "13. YouTube Title, Hook and Script", "YouTube title, hook and script prompts", """
1 Diagnose title: Examine my YouTube title and identify exactly what makes it less clickable. Evaluate its curiosity, clarity, emotional appeal, and relevance to my audience. Rewrite it into 5 stronger alternatives without changing the video's actual promise. Topic: [VIDEO TOPIC], title: [VIDEO TITLE], audience: [TARGET AUDIENCE].
2 Headlines: Generate 10 compelling YouTube titles for [VIDEO TOPIC] using curiosity, surprising outcomes, emotional triggers, and specific benefits, natural and not misleading. Audience: [TARGET AUDIENCE]. Rank your 3 strongest and explain why.
3 Story: Rewrite my YouTube script to make it more engaging from beginning to end: storytelling, pacing, no repetition, natural transitions; keep my message. Title: [VIDEO TITLE]. Script: [PASTE SCRIPT].
4 Openings: Develop 5 different opening hooks for the first 30 seconds with a strong curiosity gap and no generic intro. Topic: [VIDEO TOPIC], title: [VIDEO TITLE].
5 Retention: Identify the sections where viewers might lose interest, explain why, and rewrite them without filler. Title: [VIDEO TITLE]. Script: [PASTE SCRIPT].
6 Package: Evaluate title, thumbnail, opening and script together; list mismatches and a prioritized list of improvements. Title: [VIDEO TITLE], thumbnail: [THUMBNAIL CONCEPT].
""", kind="text", tool="ChatGPT / Claude", source="Ranajit Kodag (Facebook)")

BY_ID = {p["id"]: p for p in P}

# ───────────────────────── Asher's picker ─────────────────────────

SUBTYPES = [
    ("perfume", r"perfume|fragrance|cologne|\bedp\b|\bedt\b|eau de|body mist"),
    ("serum", r"serum|ampoule|essence|dropper|facial oil"),
    ("skincare", r"cream|lotion|toner|sunscreen|sunblock|moisturi[sz]er|cleanser|face wash|mask|skincare|soap"),
    ("makeup", r"lip|tint|blush|foundation|concealer|mascara|eyeliner|powder|cushion|makeup|palette"),
    ("bag", r"backpack|\bbag\b|tote|sling|purse|wallet|pouch|luggage"),
    ("dress", r"dress|gown|terno|filipiniana"),
    ("apparel", r"shirt|polo|blouse|\btop\b|\btee\b|pants|trousers|skirt|skort|shorts|jacket|hoodie|cardigan|jeans|leggings|ootd|\bcrop|\bset\b"),
    ("shoes", r"shoes|sandals|sneakers|heels|slippers|boots"),
    ("decor", r"decor|vase|photo frame|curtain|\blamp\b|fairy lights|string lights|christmas|parol|wreath|ornament|candle|\brug\b|wall art|plant pot|figurine"),
    ("food", r"coffee|\btea\b|snack|chips|chocolate|juice|noodle|sauce|food|cookie|candy|protein|cereal|drink"),
]


def subtype(name: str, extra: str = "") -> str:
    for text in (name, extra):
        t = (text or "").lower()
        for k, pat in SUBTYPES:
            if re.search(pat, t):
                return k
    try:
        import affiliate
        return affiliate.categorize(name, extra)
    except Exception:
        return "other"


DEFAULT_SETTING = {
    "apparel": "bright bedroom, off-white plaster wall, tall window with sheer curtains on the left, light wood floor, a full-length mirror",
    "dress": "bright bedroom, off-white plaster wall, tall window with sheer curtains on the left, light wood floor, a full-length mirror",
    "shoes": "bright minimalist room, light wood floor, cream wall, a small bench by a window on the left",
    "bag": "sunlit concrete rooftop, light from the left",
    "serum": "a white marble vanity, soft window light from the left, a small vase of dried flowers out of focus",
    "skincare": "a white marble vanity, soft window light from the left, a small vase of dried flowers out of focus",
    "makeup": "a bright vanity with a round mirror, white desk, fresh flowers, soft window light from the left",
    "perfume": "white marble, soft pastel pink and lavender background, soft diffused light from the left",
    "decor": "a cozy Filipino living room, cream sofa, oak coffee table, monstera by a window on the left",
    "food": "a light wood kitchen table, linen cloth, soft morning window light from the left",
    "home": "a bright, tidy Filipino home, light wood table, soft window light from the left, a small green plant",
    "gadgets": "a clean desk setup, light wood desk, white wall, soft window light from the left",
    "pet": "a cozy living room floor, light wood, soft window light from the left, a pet bed in the background",
}


def pick(name: str, notes: str = "", has_model: bool = False, has_bg: bool = False, colors: int = 0, inspo: bool = False) -> dict:
    """The prompt pack for one product: [{id, why}] in the order to use them."""
    st = subtype(name, notes)
    chosen: list[tuple[str, str]] = [("master", "Plano ng buong 30-second video (script, scenes, Flow prompts, CapCut)"),
                                     ("hybrid", "Para hindi magbago ang itsura ng produkto: original photo sa product shots")]
    if inspo:
        chosen.insert(1, ("recreate", "May inspo ka: i-upload ang na-download na inspo sa ChatGPT/Gemini at gayahin ang structure (hindi ang content)"))
    fashion = st in ("apparel", "dress", "shoes")
    if fashion:
        if has_model:
            chosen += [("tryon", "Damit + model: try-on display na naka-lock ang mukha, print at kwarto"),
                       ("poses_b", "Mabilis na feminine poses na may eye contact (hook)"),
                       ("poses_a", "Alternatibong pose video, mas malapad na framing")]
            if colors > 1:
                chosen.append(("colors", f"May {colors} kulay: snap transitions kada kulay"))
            chosen.append(("dress_talk" if st == "dress" else "bestie", "Nagsasalitang model para sa features"))
            chosen += [("set_front", "Realistic na photo set (front) para sa carousel o still"), ("set_side", "Side view ng parehong set")]
        else:
            chosen += [("swap1", "Walang model: model swap gamit ang selfie mo + product screenshot"), ("swap2", "Gawing video ang swap image"),
                       ("faceless", "Faceless na product video kung ayaw mo ng mukha")]
    elif st == "bag":
        chosen.append(("bag", "Bag: 6-second scroll-stopping hook montage"))
        if has_model and re.search(r"backpack|school", f"{name} {notes}", re.I):
            chosen.append(("backpack", "Backpack + model: 4-scene back-to-school recommendation"))
        chosen += [("fiveshot", "5 satisfying hands-only shots"), ("faceless", "Faceless product video")]
    elif st == "perfume":
        chosen += [("perfume1", "Hero reveal"), ("perfume2", "Luxury macro detail"), ("perfume3", "180° orbit"), ("perfume5", "Floral story")]
        if has_model:
            chosen.append(("perfume6", "Try-on test with your model"))
    elif st == "serum":
        chosen += [("serum_drip", "Hand pick-up + drip (pinakaepektibo sa serum)"), ("serum_pov", "Short POV, bote lang"),
                   ("skincare_pov" if has_bg else "fiveshot", "Skincare routine POV" if has_bg else "5 hands-only shots (walang background photo)")]
    elif st in ("skincare", "makeup"):
        chosen += [("fiveshot", "5 hands-only shots: place, glide, tap, rotate"), ("faceless", "Faceless video, puwedeng labi lang (swatch)")]
        if has_model:
            chosen += [("selfie", "Selfie UGC still na may produkto"), ("selfie_anim", "I-animate ang selfie"), ("bestie", "Bestie-tone na nagsasalita")]
    elif st == "decor":
        chosen += [("decor10", "Decor: 10-second Taglish promo, kusang pumipili ng scenes"), ("fiveshot", "5 hands-only shots")]
        if has_model:
            chosen.append(("reflock", "Ikaw/ang model sa cozy na kwarto, totoong produkto idinadagdag sa CapCut"))
    elif st == "food":
        chosen += [("fiveshot", "5 hands-only shots"), ("faceless", "Faceless na product video"),
                   ("kitchen", "Realistic na kitchen clip (camera briefing)")]
    else:
        chosen += [("fiveshot", "5 hands-only shots"), ("faceless", "Faceless na product video"),
                   ("infographic", "UGC storyboard image (6 scenes)"), ("story2video", "Gawing video ang storyboard")]
        if has_model:
            chosen.append(("reflock", "Ikaw/ang model sa lifestyle scenes, totoong produkto sa CapCut"))
    chosen += [("slash", "Mabilisang bersyon: slash command + lock line"), ("hooks", "Mga hook idea")]
    chosen += [("c0", "Lock: image roles"), ("c3a", "Lock: produkto"), ("c6", "Negative sa bawat still at clip"), ("c7", "Kapag may isang detalye na nagbago")]
    if has_model:
        chosen.insert(2, ("sheet", "Gumawa muna ng character sheet para pareho ang mukha sa lahat ng scenes"))
        chosen += [("c2", "Lock: mukha ng model")]
    chosen += [("capcut", "Final edit sa CapCut"), ("fbreels", "Caption sa FB Reels (Shopee link sa comments)"), ("hashtags", "Hashtags kada platform")]
    seen, out = set(), []
    for i, why in chosen:
        if i not in seen and i in BY_ID:
            seen.add(i)
            out.append({"id": i, "why": why})
    return {"subtype": st, "items": out}


PH = re.compile(r"\[([^\]]{1,120})\]")


def fill(text: str, values: dict) -> str:
    """Replace [PLACEHOLDERS] we know; keep the rest for the user."""
    def rep(m):
        key = re.split(r",| e\.g\.| with | \(", m.group(1))[0].strip().upper()
        return values.get(key, m.group(0))
    return PH.sub(rep, text)


def values_for(name: str, notes: str = "", model_name: str = "", setting: str = "", script: str = "", st: str = "") -> dict:
    st = st or subtype(name, notes)
    item = name or "[ITEM]"
    s = setting or DEFAULT_SETTING.get(st, DEFAULT_SETTING["home"])
    v = {"PRODUCT NAME": name, "PRODUCT": name, "ITEM": item, "PRODUCT DETAILS": notes or "[PRODUCT DETAILS]",
         "SETTING": s, "AESTHETIC BACKGROUND": s, "TABLE AND BACKGROUND": s, "ROOM": s, "ENVIRONMENT": s if st == "bag" else "[ENVIRONMENT]",
         "VOICE": "warm, mid-pitch Filipina woman, natural Taglish", "HAND DETAIL": "short nude nails, no rings"}
    if model_name:
        v.update({"MODEL NAME": model_name, "UNIQUE NAME": model_name, "CHARACTER ID": model_name})
    if script:
        v["SCRIPT"] = script
    return {k: val for k, val in v.items() if val}


def pack(name: str, notes: str = "", has_model: bool = False, model_name: str = "", has_bg: bool = False,
         colors: int = 0, script: str = "", setting: str = "", inspo: bool = False) -> dict:
    sel = pick(name, notes, has_model, has_bg, colors, inspo)
    vals = values_for(name, notes, model_name, setting, script, sel["subtype"])
    items = []
    for it in sel["items"]:
        p = BY_ID[it["id"]]
        filled = fill(p["text"], vals)
        items.append({**p, "why": it["why"], "filled": filled, "left": sorted(set(PH.findall(filled)))[:12]})
    return {"subtype": sel["subtype"], "items": items}


def render_pack(pk: dict, title: str = "") -> str:
    """HTML block (no page shell) listing the picked prompts with copy buttons."""
    import html
    e = html.escape
    rows = []
    for n, p in enumerate(pk["items"], 1):
        left = (f"<p class='muted'>Punan pa: {e(', '.join('[' + x + ']' for x in p['left']))}</p>" if p["left"] else "")
        rows.append(f"""<details class="pp"{' open' if n <= 3 else ''}><summary><b>{n}. {e(p['title'])}</b> <span class="tag">{e(p['tool'])}</span>
<span class="muted">· {e(p['why'])}</span></summary>
{('<p class="muted">Kailangan: ' + e(', '.join(p['needs'])) + '</p>') if p['needs'] else ''}{left}
<pre>{e(p['filled'])}</pre><button class="copy" type="button">📋 Copy prompt</button>
{('<p class="muted">' + e(p['note']) + '</p>') if p['note'] else ''}</details>""")
    return (f"<section class='ppack'><h2>🎬 Prompt Pack{(': ' + e(title)) if title else ''} "
            f"<span class='tag'>picked by Asher · {e(pk['subtype'])}</span></h2>"
            "<p class='muted'>Pinili mula sa Prompt Library mo ayon sa uri ng produkto at sa mga meron ka (model, photos, background). "
            "Puno na ang mga alam na [placeholder]. <a href='/prompts' target='_blank'>📚 Buong library</a></p>" + "".join(rows) + "</section>")


PACK_CSS = """.ppack{margin-top:18px}.ppack h2{font-size:18px}.pp{background:rgba(0,0,0,.18);border-radius:10px;padding:8px 12px;margin:6px 0}
.pp summary{cursor:pointer}.pp pre{white-space:pre-wrap;font:13px/1.45 ui-monospace,Menlo,monospace;background:rgba(0,0,0,.25);padding:10px;border-radius:8px;max-height:420px;overflow:auto}
.tag{display:inline-block;font-size:11px;background:rgba(255,255,255,.12);border-radius:99px;padding:1px 8px;margin-left:4px}"""
COPY_JS = """document.addEventListener('click',e=>{const b=e.target.closest('button.copy');if(!b)return;const pre=b.parentElement.querySelector('pre');if(!pre)return;
navigator.clipboard.writeText(pre.innerText);const t=b.textContent;b.textContent='Copied ✅';setTimeout(()=>b.textContent=t,1500)});"""


def render_library() -> str:
    import html
    e = html.escape
    secs: dict[str, list] = {}
    for p in P:
        secs.setdefault(p["section"], []).append(p)
    body = []
    for sec, ps in secs.items():
        items = "".join(f"""<details class="pp" data-q="{e((p['title'] + ' ' + p['text']).lower())}"><summary><b>{e(p['title'])}</b> <span class="tag">{e(p['kind'])}</span>
<span class="tag">{e(p['tool'])}</span>{(' <span class="muted">· ' + e(p['source']) + '</span>') if p['source'] else ''}</summary>
{('<p class="muted">Kailangan: ' + e(', '.join(p['needs'])) + '</p>') if p['needs'] else ''}<pre>{e(p['text'])}</pre><button class="copy" type="button">📋 Copy</button>
{('<p class="muted">' + e(p['note']) + '</p>') if p['note'] else ''}</details>""" for p in ps)
        body.append(f"<h2>{e(sec)}</h2>{items}")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>📚 Prompt Library</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{font:15px/1.5 system-ui,sans-serif;background:#0b2a3a;color:#eafaff;margin:0;padding:22px;max-width:1000px;margin:auto}}
.muted{{color:#9cc7d6;font-size:13px}} input{{width:100%;padding:10px;border-radius:10px;border:1px solid #1f6a86;background:#06202c;color:#fff;font-size:15px}}
button.copy{{background:#ffd23d;color:#2a1a00;border:0;border-radius:8px;padding:6px 10px;font-weight:700;cursor:pointer}} {PACK_CSS}</style></head>
<body><h1>📚 Prompt Library</h1><p class="muted">{len(P)} prompts mula sa koleksyon mo (optimized for strict consistency). Si Asher ang pumipili para sa bawat produkto sa Content Hub at Affiliate Studio.
Wala rito ang mga setup na hindi pang-produkto (herk-edit-kit, Context Transfer skill, 7 ChatGPT modes).</p>
<input id="q" placeholder="🔎 Hanapin: serum, bag, perfume, model, CapCut…"> {''.join(body)}
<script>{COPY_JS} document.getElementById('q').oninput=e=>{{const q=e.target.value.toLowerCase();document.querySelectorAll('details.pp').forEach(d=>d.style.display=!q||d.dataset.q.includes(q)?'':'none')}};</script></body></html>"""
