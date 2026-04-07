import React, { useEffect, useState } from "react"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Slider } from "@/components/ui/slider"
import { cn } from "@/lib/utils"
import { hexToRgb, parseRgba, rgbaToHex } from "@/lib/colors"

interface ColorPickerProps {
    color: string // Can be hex or rgba
    onChange: (color: string) => void
    label?: string
    supportOpacity?: boolean
}

export function ColorPicker({ color, onChange, label, supportOpacity = false }: ColorPickerProps) {
    const [hex, setHex] = useState("#FFFFFF")
    const [alpha, setAlpha] = useState(1.0)

    // Sync internal state with prop
    useEffect(() => {
        if (color.startsWith("rgba")) {
            const { r, g, b, a } = parseRgba(color)
            setHex(rgbaToHex(r, g, b))
            setAlpha(a)
        } else {
            setHex(color)
            setAlpha(1.0) // Reset alpha if color changes to hex
        }
    }, [color])

    const handleHexChange = (newHex: string) => {
        setHex(newHex)
        if (supportOpacity) {
            const { r, g, b } = hexToRgb(newHex)
            onChange(`rgba(${r}, ${g}, ${b}, ${alpha})`)
        } else {
            onChange(newHex)
        }
    }

    const handleAlphaChange = (newAlpha: number) => {
        setAlpha(newAlpha)
        const { r, g, b } = hexToRgb(hex)
        onChange(`rgba(${r}, ${g}, ${b}, ${newAlpha})`)
    }

    return (
        <div className="space-y-2">
            {label && <Label className="text-xs font-semibold">{label}</Label>}
            <Popover>
                <PopoverTrigger asChild>
                    <Button
                        variant="outline"
                        className="w-full justify-start text-left font-normal px-2"
                    >
                        <div
                            className="w-4 h-4 rounded-full mr-2 border border-muted-foreground/20 shadow-sm"
                            style={{ backgroundColor: color }}
                        />
                        <span className="truncate flex-1 text-xs text-muted-foreground">{color}</span>
                    </Button>
                </PopoverTrigger>
                <PopoverContent className="w-64 p-4">
                    <div className="space-y-4">
                        <div>
                            <Label className="text-xs mb-2 block text-muted-foreground">Color</Label>
                            <div className="flex gap-2">
                                <Input
                                    type="color"
                                    value={hex}
                                    onChange={(e) => handleHexChange(e.target.value)}
                                    className="w-8 h-8 p-0 border-0 rounded overflow-hidden cursor-pointer shrink-0"
                                />
                                <Input
                                    value={hex}
                                    onChange={(e) => handleHexChange(e.target.value)}
                                    className="flex-1 h-8 text-xs font-mono uppercase"
                                />
                            </div>
                        </div>

                        {supportOpacity && (
                            <div>
                                <Label className="text-xs mb-2 block text-muted-foreground">Opacity: {Math.round(alpha * 100)}%</Label>
                                <Slider
                                    value={[alpha]}
                                    min={0}
                                    max={1} // Max should be 1 for alpha
                                    step={0.01} // Step should be smaller for finer control
                                    onValueChange={(vals) => handleAlphaChange(vals[0])}
                                    className="py-2"
                                />
                            </div>
                        )}
                    </div>
                </PopoverContent>
            </Popover>
        </div>
    )
}
