// Utility to parse RGBA and manipulate opacity
export function parseRgba(rgba: string) {
    const parts = rgba.replace("rgba(", "").replace(")", "").split(",").map(s => s.trim());
    if (parts.length < 4) return { r: 0, g: 0, b: 0, a: 1 };
    return {
        r: parseInt(parts[0]),
        g: parseInt(parts[1]),
        b: parseInt(parts[2]),
        a: parseFloat(parts[3])
    };
}

export function rgbaToHex(r: number, g: number, b: number) {
    return "#" + [r, g, b].map(x => {
        const hex = x.toString(16);
        return hex.length === 1 ? "0" + hex : hex;
    }).join("");
}

export function hexToRgb(hex: string) {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    return result ? {
        r: parseInt(result[1], 16),
        g: parseInt(result[2], 16),
        b: parseInt(result[3], 16)
    } : { r: 0, g: 0, b: 0 };
}
