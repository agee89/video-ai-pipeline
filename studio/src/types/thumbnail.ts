export interface ThumbnailConfig {
    text_overlay: {
        text: string;
        style: {
            font_family: string;
            font_weight: string;
            stroke_color: string;
            stroke_width: number;
            font_size: number;
            letter_spacing: number;
            line_height: number;
            color: string;
            text_transform: "capitalize" | "uppercase" | "lowercase" | "none";
            text_shadow: string;
        };
        background: {
            enabled: boolean;
            full_width: boolean;
            radius: number;
            gradient: boolean;
            gradient_height: number;
            color: string; // rgba string
        };
        position: {
            y: "bottom" | "center" | "top";
            margin_bottom: number;
            edge_padding: number;
            max_lines: number;
        };
    };
}

export const DEFAULT_THUMB_CONFIG: ThumbnailConfig = {
    text_overlay: {
        text: "", // Will be filled from title
        style: {
            font_family: "Komika Axis",
            font_weight: "bold",
            stroke_color: "#333333",
            stroke_width: 2,
            font_size: 100,
            letter_spacing: 1,
            line_height: 1.2,
            color: "#FFFFFF",
            text_transform: "capitalize",
            text_shadow: "10px 10px 0px #904F26",
        },
        background: {
            enabled: true,
            full_width: true,
            radius: 0,
            gradient: true,
            gradient_height: 1000,
            color: "rgba(255, 170, 0, 1.9)",
        },
        position: {
            y: "bottom",
            margin_bottom: 150,
            edge_padding: 10,
            max_lines: 4,
        },
    },
};
