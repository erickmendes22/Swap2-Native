#version 450
// Snapdragon Game Super Resolution 1 spatial upscaler, adapted for Vulkan
// viewport crops and NVN's lower-left render targets.
// Original algorithm: Qualcomm Innovation Center / Snapdragon Game Studios,
// SPDX-License-Identifier: BSD-3-Clause. Spatial 12-tap adaptive luma detail
// reconstruction and sharpening, performed in a SINGLE render pass.
// The push constants and descriptor layout match the existing FSR EASU shader;
// no new descriptor bindings or game shader library are required.
layout(set = 0, binding = 0) uniform sampler2D tex;
layout(push_constant) uniform P { uvec4 con0, con1, con2, con3; } pc;
layout(location = 0) out vec4 fragColour;

float fastLanczos2(float x) {
    float wA = x - 4.0;
    float wB = x*wA - wA;
    return wB*wA*wA;
}
vec2 detailWeight(float dx, float dy, float contrast, float inverseContrast) {
    float r = (dx*dx + dy*dy) * 0.55 + clamp(abs(contrast)*inverseContrast, 0.0, 1.0);
    float weight = fastLanczos2(r);
    return vec2(weight, weight * contrast);
}

void main() {
    ivec2 dims = textureSize(tex, 0);
    if (dims.x <= 0 || dims.y <= 0) { fragColour = vec4(0,0,0,1); return; }

    // FSR con0: source pixel = destination pixel * scale + offset.
    // The destination pixel is floor(gl_FragCoord), so the first texel is
    // reconstructed at source pixel 0, NOT at half-pixel + 0.5 displacement.
    vec4 transform = uintBitsToFloat(pc.con0);
    vec2 srcPix = vec2(ivec2(gl_FragCoord.xy))*transform.xy + transform.zw;
    vec2 inv = 1.0 / vec2(dims);
    vec2 uv = (srcPix + 0.5) * inv;
    vec3 color = textureLod(tex, clamp(uv, vec2(0), vec2(1)), 0.0).rgb;

    // SGSR1 uses green as its fast luma proxy; gathers all 12 neighbours at
    // once through Adreno's native gather instructions, only around edges.
    vec2 pixel = floor(srcPix);
    vec2 xy = pixel * inv;
    vec4 left = textureGather(tex, clamp(xy, vec2(0), vec2(1)), 1);
    float edgeVote = abs(left.z-left.y) + abs(color.g-left.y) + abs(color.g-left.z);
    if (edgeVote > (8.0/255.0)) {
        xy.x += inv.x;
        vec4 right = textureGather(tex, clamp(xy+vec2(inv.x,0), vec2(0),vec2(1)), 1);
        vec4 upDown;
        upDown.xy = textureGather(tex, clamp(xy+vec2(0,-inv.y),vec2(0),vec2(1)), 1).wz;
        upDown.zw = textureGather(tex, clamp(xy+vec2(0, inv.y),vec2(0),vec2(1)), 1).yx;

        float mean = (left.y + left.z + right.x + right.w)*0.25;
        left -= vec4(mean);
        right -= vec4(mean);
        upDown -= vec4(mean);
        float lum = color.g-mean;
        float variation = abs(left.x)+abs(left.y)+abs(left.z)+abs(left.w)
                        + abs(right.x)+abs(right.y)+abs(right.z)+abs(right.w)
                        + abs(upDown.x)+abs(upDown.y)+abs(upDown.z)+abs(upDown.w);
        float norm = 2.181818 / max(variation, 1e-6);
        vec2 p = fract(srcPix);
        vec2 w = detailWeight(p.x, p.y+1.0, upDown.x,norm);
        w += detailWeight(p.x-1.0,p.y+1.0,upDown.y,norm);
        w += detailWeight(p.x-1.0,p.y-2.0,upDown.z,norm);
        w += detailWeight(p.x,p.y-2.0,upDown.w,norm);
        w += detailWeight(p.x+1.0,p.y-1.0,left.x,norm);
        w += detailWeight(p.x,p.y-1.0,left.y,norm);
        w += detailWeight(p.x,p.y,left.z,norm);
        w += detailWeight(p.x+1.0,p.y,left.w,norm);
        w += detailWeight(p.x-1.0,p.y-1.0,right.x,norm);
        w += detailWeight(p.x-2.0,p.y-1.0,right.y,norm);
        w += detailWeight(p.x-2.0,p.y,right.z,norm);
        w += detailWeight(p.x-1.0,p.y,right.w,norm);

        float reconstructed = w.y / max(w.x, 1e-6);
        float maxY = max(max(left.y,left.z),max(right.x,right.w));
        float minY = min(min(left.y,left.z),min(right.x,right.w));
        float change = clamp(2.0*reconstructed, minY, maxY) - lum;
        color = clamp(color + clamp(change, -23.0/255.0, 23.0/255.0), 0.0, 1.0);
    }
    fragColour = vec4(color, 1.0);
}
