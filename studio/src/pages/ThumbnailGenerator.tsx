
import { useState, useMemo } from "react"
import { useMutation } from "@tanstack/react-query"
import {
    Search, Loader2, Sparkles, Wand2, LayoutTemplate,
    MonitorPlay, Type, Sliders, Play, Settings2, Image as ImageIcon,
    ChevronDown, Video
} from "lucide-react"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { ColorPicker } from "@/components/ui/color-picker"
import { getVideoInfo, type YouTubeInfo } from "@/lib/api"
import { cn } from "@/lib/utils"

// Types
import { DEFAULT_STUDIO_STATE, type StudioState, type CameraConfig, type CaptionConfig } from "@/types/studio"
import { type ThumbnailConfig } from "@/types/thumbnail"

export default function ThumbnailGenerator() {
    // Top Level State
    const [url, setUrl] = useState("")
    const [info, setInfo] = useState<YouTubeInfo | null>(null)
    const [hasLoaded, setHasLoaded] = useState(false)
    const [previewTab, setPreviewTab] = useState<'thumbnail' | 'caption'>('thumbnail')

    // Global Studio State
    const [state, setState] = useState<StudioState>(DEFAULT_STUDIO_STATE)

    // Accessors for convenience
    const config = state.thumbnail
    const camConfig = state.camera
    const capConfig = state.caption

    // --- ACTIONS ---
    const updateThumbnail = (section: keyof ThumbnailConfig['text_overlay'], key: string, value: any) => {
        setState(prev => ({
            ...prev,
            thumbnail: {
                ...prev.thumbnail,
                text_overlay: {
                    ...prev.thumbnail.text_overlay,
                    [section]: {
                        ...prev.thumbnail.text_overlay[section as "style" | "background" | "position"],
                        [key]: value
                    }
                }
            }
        }))
    }

    const updateThumbRoot = (val: string) => {
        setState(prev => ({
            ...prev,
            thumbnail: { ...prev.thumbnail, text_overlay: { ...prev.thumbnail.text_overlay, text: val } }
        }))
    }

    const updateCamera = (key: keyof CameraConfig, value: any) => {
        setState(prev => ({
            ...prev,
            camera: { ...prev.camera, [key]: value }
        }))
    }

    const updateCaption = (key: keyof CaptionConfig['settings'], value: any) => {
        setState(prev => ({
            ...prev,
            caption: {
                ...prev.caption,
                settings: { ...prev.caption.settings, [key]: value }
            }
        }))
    }

    const updateTranscript = (val: string) => {
        setState(prev => ({ ...prev, transcript: val }))
    }

    // --- API Fetch ---
    const fetchMutation = useMutation({
        mutationFn: getVideoInfo,
        onSuccess: (data) => {
            setInfo(data)
            setHasLoaded(true)

            // Auto-populate
            setState(prev => ({
                ...prev,
                transcript: data.transcript || "",
                thumbnail: {
                    ...prev.thumbnail,
                    text_overlay: {
                        ...prev.thumbnail.text_overlay,
                        text: prev.thumbnail.text_overlay.text || data.title
                    }
                }
            }))
        },
        onError: (error) => {
            console.error(error)
            alert("Failed to fetch video info. " + error)
        },
    })

    const handleFetch = (e: React.FormEvent) => {
        e.preventDefault()
        if (!url) return
        fetchMutation.mutate(url)
    }

    // --- Generate Webhook ---
    const generateMutation = useMutation({
        mutationFn: async (payload: any) => {
            const webhookUrl = import.meta.env.VITE_N8N_WEBHOOK_URL || "http://localhost:5678/webhook/test"
            const response = await fetch(webhookUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
            if (!response.ok) throw new Error("Webhook failed")
            return response.json()
        },
        onSuccess: () => alert("Job Submitted Successfully!"),
        onError: (err) => alert("Error submitting job: " + err.message)
    })

    const handleGenerate = () => {
        if (!info || !url) return
        const payload = {
            youtube_url: url,
            channel_name: info.channel,
            transcript: state.transcript,
            parameters: camConfig,
            caption_conf: capConfig,
            thumbnail_conf: config
        }
        console.log("Submitting Payload:", payload)
        generateMutation.mutate(payload)
    }

    // --- PREVIEW LOGIC (THUMBNAIL) ---
    const thumbPreviewStyles = useMemo(() => {
        const SCALE = 0.25
        const style = config.text_overlay.style
        const bg = config.text_overlay.background
        const pos = config.text_overlay.position

        // Font
        const fontSize = Math.floor(style.font_size * SCALE)
        const strokeW = Math.max(0, style.stroke_width * SCALE * 2)
        const webkitStroke = strokeW > 0 ? `${strokeW}px ${style.stroke_color}` : undefined
        const letterSpacing = `${style.letter_spacing * SCALE}px`
        const shadowColor = style.text_shadow.includes(' ') ? style.text_shadow.split(' ').pop() : style.text_shadow
        const textShadow = `2.5px 2.5px 0px ${shadowColor || '#904F26'}`

        // Alignment
        const scaledMargin = Math.floor(pos.margin_bottom * SCALE)
        let alignItems = "flex-end" // Vertical
        let marginTop = "0px", marginBottom = "0px"

        if (pos.y === "top") { alignItems = "flex-start"; marginTop = `${scaledMargin}px` }
        else if (pos.y === "center") { alignItems = "center" }
        else { alignItems = "flex-end"; marginBottom = `${scaledMargin}px` }

        // Background
        const BG_PAD = 40
        const boxPad = `${Math.floor(BG_PAD * SCALE)}px`
        let bgStyle: React.CSSProperties = {}
        if (bg.enabled && !bg.gradient) {
            bgStyle = { backgroundColor: bg.color, borderRadius: '4px', width: bg.full_width ? '100%' : 'auto' }
        }

        // Gradient
        let gradientStyle: React.CSSProperties = { display: 'none' }
        if (bg.enabled && bg.gradient) {
            gradientStyle = {
                display: 'block', position: 'absolute', bottom: 0, left: 0, width: '100%',
                height: `${Math.floor(bg.gradient_height * SCALE)}px`,
                background: `linear-gradient(to top, ${bg.color} 50%, transparent 100%)`, zIndex: 1
            }
        }

        return {
            container: { display: 'flex', flexDirection: 'column' as const, justifyContent: alignItems, alignItems: 'center' },
            box: { marginTop, marginBottom, padding: boxPad, ...bgStyle, zIndex: 2, textAlign: 'center' as const },
            text: {
                fontFamily: style.font_family, fontSize: `${fontSize}px`, fontWeight: style.font_weight === "bold" ? 700 : 400,
                color: style.color, lineHeight: style.line_height, letterSpacing, WebkitTextStroke: webkitStroke, textShadow,
                textTransform: style.text_transform === "none" ? undefined : style.text_transform,
                display: '-webkit-box', WebkitLineClamp: pos.max_lines, WebkitBoxOrient: 'vertical' as const, overflow: 'hidden'
            },
            gradient: gradientStyle
        }
    }, [config])

    // --- PREVIEW LOGIC (CAPTION) ---
    const capPreviewStyles = useMemo(() => {
        const SCALE = 0.25
        const FONT_SCALE_CORRECTION = 0.615
        const s = capConfig.settings

        // Font
        const fontSize = Math.floor(s.font_size * SCALE * FONT_SCALE_CORRECTION)
        const scaledMargin = Math.floor(s.margin_v * SCALE)
        // CSS text-stroke is centered, so we roughly need 2x to match outer border look, 
        // effectively 0.5 * width on outside. Matches Python logic.
        const scaledOutline = Math.max(0, s.outline_width * SCALE * 2)

        const webkitStroke = scaledOutline > 0 ? `${scaledOutline}px ${s.outline_color}` : undefined

        // Alignment Mappings for Flex-Column
        // Default: Bottom Center
        let justifyContent = "flex-end" // Vertical (Main Axis)
        let alignItems = "center"       // Horizontal (Cross Axis)
        let textAlign: React.CSSProperties['textAlign'] = "center"
        let marginTop = "0px", marginBottom = "0px"

        const pos = s.position || "bottom_center"

        // Vertical Logic
        if (pos.includes("top")) {
            justifyContent = "flex-start";
            marginTop = `${scaledMargin}px`
        } else if (pos === "center") {
            justifyContent = "center"
        } else {
            // Bottom
            justifyContent = "flex-end";
            marginBottom = `${scaledMargin}px`
        }

        // Horizontal Logic
        if (pos.includes("left")) {
            alignItems = "flex-start";
            textAlign = "left"
        } else if (pos.includes("right")) {
            alignItems = "flex-end";
            textAlign = "right"
        } else {
            alignItems = "center";
            textAlign = "center"
        }

        // Mock Text Generation
        const rawText = "SAMPLE CAPTION TEXT GENERATION"
        const words = (s.all_caps ? rawText.toUpperCase() : rawText).split(' ')

        // Simulate line breaks based on max_words
        const lines: string[][] = []
        for (let i = 0; i < words.length; i += s.max_words_per_line) {
            lines.push(words.slice(i, i + s.max_words_per_line))
        }

        return {
            container: {
                display: 'flex', flexDirection: 'column' as const,
                justifyContent, alignItems,
                position: 'absolute' as const, inset: 0, pointerEvents: 'none' as const,
                zIndex: 10
            },
            textBox: {
                marginTop, marginBottom, textAlign, width: '100%', padding: '10px'
            },
            text: {
                fontFamily: s.font_family, fontSize: `${fontSize}px`,
                fontWeight: s.bold ? 'bold' : 'normal',
                fontStyle: s.italic ? 'italic' : 'normal',
                color: s.line_color,
                WebkitTextStroke: webkitStroke,
                lineHeight: 1.2,
                margin: 0
            },
            wordHighlight: { color: s.word_color },
            lines
        }
    }, [capConfig])


    // --- RENDER: SEARCH STAGE ---
    if (!hasLoaded) {
        return (
            <div className="flex h-screen w-full items-center justify-center bg-background px-4 relative overflow-hidden">
                <div className="absolute inset-0 bg-grid-black/[0.02] dark:bg-grid-white/[0.02] bg-[length:50px_50px]" />
                <div className="absolute h-full w-full bg-background [mask-image:radial-gradient(ellipse_at_center,transparent_20%,black)]" />

                <div className="z-10 w-full max-w-2xl space-y-8 text-center animate-in fade-in zoom-in duration-500">
                    <div className="space-y-4">
                        <div className="inline-flex items-center justify-center p-4 rounded-2xl bg-primary/10 text-primary mb-4 ring-1 ring-primary/20 shadow-[0_0_50px_-12px_var(--primary)]">
                            <MonitorPlay className="h-10 w-10" />
                        </div>
                        <h1 className="text-4xl md:text-5xl font-bold tracking-tight bg-gradient-to-b from-foreground to-foreground/60 bg-clip-text text-transparent">
                            What are we clipping today?
                        </h1>
                        <p className="text-muted-foreground text-lg max-w-lg mx-auto">
                            Transform YouTube videos into viral shorts with AI-powered captions, tracking, and thumbnails.
                        </p>
                    </div>

                    <form onSubmit={handleFetch} className="relative max-w-lg mx-auto">
                        <div className="relative group">
                            <div className="absolute -inset-1 bg-gradient-to-r from-indigo-500 to-purple-600 rounded-xl blur opacity-20 group-hover:opacity-40 transition duration-1000"></div>
                            <div className="relative flex items-center">
                                <Search className="absolute left-4 h-5 w-5 text-muted-foreground" />
                                <input
                                    type="text"
                                    value={url}
                                    onChange={e => setUrl(e.target.value)}
                                    placeholder="Paste YouTube URL here..."
                                    className="w-full h-14 bg-background/90 border border-input rounded-xl pl-12 pr-12 text-lg focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary/50 transition-all placeholder:text-muted-foreground"
                                    autoFocus
                                />
                                <div className="absolute right-2">
                                    <Button
                                        type="submit"
                                        size="icon"
                                        className="h-10 w-10 rounded-lg bg-primary hover:bg-primary/90 transition-all shadow-lg shadow-primary/20"
                                        disabled={fetchMutation.isPending}
                                    >
                                        {fetchMutation.isPending ? <Loader2 className="h-5 w-5 animate-spin" /> : <Play className="h-5 w-5 fill-current" />}
                                    </Button>
                                </div>
                            </div>
                        </div>
                    </form>

                    <div className="flex gap-4 justify-center text-xs text-muted-foreground/50 font-mono">
                        <span>AI CAPTIONS</span>
                        <span>•</span>
                        <span>FACE TRACKING</span>
                        <span>•</span>
                        <span>THUMBNAILS</span>
                    </div>
                </div>
            </div>
        )
    }

    // --- RENDER: WORKSPACE STAGE ---
    return (
        <div className="flex h-screen w-full bg-background overflow-hidden">
            {/* 1. LEFT PANEL: SOURCE & SETTINGS (25%) */}
            <div className="w-[380px] border-r border-border bg-card/50 flex flex-col h-full z-10">
                {/* Header Info */}
                <div className="p-4 border-b border-border space-y-4 shrink-0">
                    <div className="flex gap-3">
                        <div className="h-20 w-32 shrink-0 rounded-lg overflow-hidden ring-1 ring-border bg-muted relative group">
                            <img src={info?.thumbnail} className="h-full w-full object-cover opacity-80 group-hover:opacity-100 transition" />
                        </div>
                        <div className="space-y-1 overflow-hidden">
                            <h2 className="font-semibold text-sm line-clamp-2 leading-tight">{info?.title}</h2>
                            <p className="text-xs text-muted-foreground flex items-center gap-1">
                                <ImageIcon className="h-3 w-3" /> {info?.channel}
                            </p>
                        </div>
                    </div>

                    <div className="flex gap-2">
                        <div className="relative flex-1">
                            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
                            <Input value={url} onChange={e => setUrl(e.target.value)} className="h-9 pl-8 text-xs bg-background/50" />
                        </div>
                        <Button size="sm" variant="outline" className="h-9 px-3" onClick={handleFetch}>
                            {fetchMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Reload"}
                        </Button>
                    </div>
                </div>

                {/* SCROLLABLE SETTINGS */}
                <div className="flex-1 overflow-y-auto p-4 space-y-6 scrollbar-thin scrollbar-thumb-white/10">

                    {/* TRANSCRIPT */}
                    <div className="space-y-3">
                        <div className="flex items-center gap-2 text-primary/80">
                            <Type className="h-3.5 w-3.5" />
                            <Label className="text-xs font-bold uppercase tracking-wider">Transcript</Label>
                        </div>
                        <textarea
                            className="w-full h-32 bg-background/30 border border-input rounded-md p-3 text-xs text-muted-foreground focus:outline-none focus:border-primary/50 resize-none font-mono leading-relaxed"
                            value={state.transcript}
                            onChange={e => updateTranscript(e.target.value)}
                            placeholder="Transcript text will appear here..."
                        />
                    </div>

                    <div className="h-px bg-border" />

                    {/* CAMERA SETTINGS */}
                    <div className="space-y-4">
                        <div className="flex items-center justify-between text-primary/80">
                            <div className="flex items-center gap-2">
                                <Video className="h-3.5 w-3.5" />
                                <Label className="text-xs font-bold uppercase tracking-wider">AI Cameraman</Label>
                            </div>
                            <Switch checked={camConfig.face_tracking} onCheckedChange={c => updateCamera('face_tracking', c)} />
                        </div>

                        {camConfig.face_tracking && (
                            <div className="space-y-4 pl-2 border-l border-border ml-1 animate-in slide-in-from-left-2 duration-300">
                                <div className="grid grid-cols-2 gap-3">
                                    <div className="space-y-1.5">
                                        <Label className="text-[10px] text-muted-foreground">Sensitivity ({camConfig.tracking_sensitivity})</Label>
                                        <Slider value={[camConfig.tracking_sensitivity]} min={1} max={10} step={1} onValueChange={([v]) => updateCamera('tracking_sensitivity', v)} />
                                    </div>
                                    <div className="space-y-1.5">
                                        <Label className="text-[10px] text-muted-foreground">Smoothing ({camConfig.camera_smoothing})</Label>
                                        <Slider value={[camConfig.camera_smoothing]} min={0.05} max={0.5} step={0.05} onValueChange={([v]) => updateCamera('camera_smoothing', v)} />
                                    </div>
                                    <div className="space-y-1.5">
                                        <Label className="text-[10px] text-muted-foreground">Zoom Thresh ({camConfig.zoom_threshold})</Label>
                                        <Slider value={[camConfig.zoom_threshold]} min={5} max={30} step={1} onValueChange={([v]) => updateCamera('zoom_threshold', v)} />
                                    </div>
                                    <div className="space-y-1.5">
                                        <Label className="text-[10px] text-muted-foreground">Zoom Level ({camConfig.zoom_level})</Label>
                                        <Slider value={[camConfig.zoom_level]} min={1.0} max={1.5} step={0.05} onValueChange={([v]) => updateCamera('zoom_level', v)} />
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>

                    <div className="h-px bg-border" />

                    {/* CAPTION SETTINGS (VIDEO) */}
                    <div className="space-y-4">
                        <div className="flex items-center gap-2 text-primary/80">
                            <Settings2 className="h-3.5 w-3.5" />
                            <Label className="text-xs font-bold uppercase tracking-wider">Video Captions</Label>
                        </div>

                        <div className="space-y-3 pl-2 border-l border-border ml-1">
                            <div className="grid grid-cols-2 gap-2">
                                <div className="space-y-1">
                                    <Label className="text-[10px] text-muted-foreground">Font</Label>
                                    <Select value={capConfig.settings.font_family} onValueChange={v => updateCaption('font_family', v)}>
                                        <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value="Komika Axis">Komika Axis</SelectItem>
                                            <SelectItem value="Montserrat">Montserrat</SelectItem>
                                            <SelectItem value="Arial">Arial</SelectItem>
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div className="space-y-1">
                                    <Label className="text-[10px] text-muted-foreground">Size ({capConfig.settings.font_size})</Label>
                                    <Input type="number" className="h-8 text-xs" value={capConfig.settings.font_size} onChange={e => updateCaption('font_size', Number(e.target.value))} />
                                </div>
                            </div>

                            <div className="grid grid-cols-3 gap-2">
                                <ColorPicker label="Text" color={capConfig.settings.line_color} onChange={c => updateCaption('line_color', c)} />
                                <ColorPicker label="Active" color={capConfig.settings.word_color} onChange={c => updateCaption('word_color', c)} />
                                <ColorPicker label="Outline" color={capConfig.settings.outline_color} onChange={c => updateCaption('outline_color', c)} />
                            </div>

                            <div className="grid grid-cols-2 gap-2">
                                <div className="flex items-center gap-2 border border-input rounded px-2 h-8">
                                    <Switch id="cap-bold" checked={capConfig.settings.bold} onCheckedChange={c => updateCaption('bold', c)} className="scale-75" />
                                    <Label htmlFor="cap-bold" className="text-[10px] cursor-pointer">BOLD</Label>
                                </div>
                                <div className="flex items-center gap-2 border border-input rounded px-2 h-8">
                                    <Switch id="cap-caps" checked={capConfig.settings.all_caps} onCheckedChange={c => updateCaption('all_caps', c)} className="scale-75" />
                                    <Label htmlFor="cap-caps" className="text-[10px] cursor-pointer">ALL CAPS</Label>
                                </div>
                            </div>
                            <div className="grid grid-cols-2 gap-2">
                                <div className="space-y-1">
                                    <Label className="text-[10px] text-muted-foreground">Position</Label>
                                    <Select value={capConfig.settings.position} onValueChange={v => updateCaption('position', v)}>
                                        <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value="bottom_center">Bot Ctr</SelectItem>
                                            <SelectItem value="bottom_left">Bot Left</SelectItem>
                                            <SelectItem value="bottom_right">Bot Right</SelectItem>
                                            <SelectItem value="center">Center</SelectItem>
                                            <SelectItem value="top_center">Top Ctr</SelectItem>
                                            <SelectItem value="top_left">Top Left</SelectItem>
                                            <SelectItem value="top_right">Top Right</SelectItem>
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div className="space-y-1">
                                    <Label className="text-[10px] text-muted-foreground">V-Margin ({capConfig.settings.margin_v})</Label>
                                    <Slider value={[capConfig.settings.margin_v]} min={0} max={600} step={10} onValueChange={([v]) => updateCaption('margin_v', v)} />
                                </div>
                            </div>

                            <div className="grid grid-cols-2 gap-2">
                                <div className="space-y-1">
                                    <Label className="text-[10px] text-muted-foreground">Outline ({capConfig.settings.outline_width})</Label>
                                    <Slider value={[capConfig.settings.outline_width]} min={0} max={50} step={1} onValueChange={([v]) => updateCaption('outline_width', v)} />
                                </div>
                                <div className="space-y-1">
                                    <Label className="text-[10px] text-muted-foreground">Max Words ({capConfig.settings.max_words_per_line})</Label>
                                    <Slider value={[capConfig.settings.max_words_per_line]} min={1} max={10} step={1} onValueChange={([v]) => updateCaption('max_words_per_line', v)} />
                                </div>
                            </div>

                            <div className="grid grid-cols-2 gap-2">
                                <div className="flex items-center gap-2 border border-input rounded px-2 h-8">
                                    <Switch id="cap-bold" checked={capConfig.settings.bold} onCheckedChange={c => updateCaption('bold', c)} className="scale-75" />
                                    <Label htmlFor="cap-bold" className="text-[10px] cursor-pointer">BOLD</Label>
                                </div>
                                <div className="flex items-center gap-2 border border-input rounded px-2 h-8">
                                    <Switch id="cap-caps" checked={capConfig.settings.all_caps} onCheckedChange={c => updateCaption('all_caps', c)} className="scale-75" />
                                    <Label htmlFor="cap-caps" className="text-[10px] cursor-pointer">ALL CAPS</Label>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* 2. MIDDLE: PREVIEW STAGE (50%) */}
            <div className="flex-1 flex flex-col relative bg-muted/30 overflow-hidden">
                <div className="absolute inset-0 opacity-[0.03] dark:invert" style={{ backgroundImage: `linear-gradient(#000 1px, transparent 1px), linear-gradient(90deg, #000 1px, transparent 1px)`, backgroundSize: '40px 40px' }} />

                <div className="flex-1 flex flex-col items-center justify-center p-8 relative">
                    {/* PREVIEW TABS */}
                    <div className="flex items-center bg-muted/50 p-1 rounded-lg mb-6 border border-border">
                        <button
                            onClick={() => setPreviewTab('caption')}
                            className={cn(
                                "flex-1 px-6 py-2 rounded-md text-xs font-medium transition-all",
                                previewTab === 'caption' ? "bg-background text-foreground shadow-sm ring-1 ring-border" : "text-muted-foreground hover:text-foreground hover:bg-background/50"
                            )}
                        >
                            Caption
                        </button>
                        <button
                            onClick={() => setPreviewTab('thumbnail')}
                            className={cn(
                                "flex-1 px-6 py-2 rounded-md text-xs font-medium transition-all",
                                previewTab === 'thumbnail' ? "bg-background text-foreground shadow-sm ring-1 ring-border" : "text-muted-foreground hover:text-foreground hover:bg-background/50"
                            )}
                        >
                            Thumbnail
                        </button>
                    </div>

                    {/* PREVIEW CONTAINER */}
                    <div
                        className="relative bg-black shadow-2xl rounded-lg overflow-hidden shrink-0 ring-1 ring-white/10 transition-all duration-300"
                        style={{
                            width: '270px',
                            height: `${270 * 16 / 9}px`, // 480px
                            backgroundImage: info ? `url(${info.thumbnail})` : 'none',
                            backgroundSize: 'cover',
                            backgroundPosition: 'center',
                            ...thumbPreviewStyles.container
                        }}
                    >
                        {/* THUMBNAIL LAYERS */}
                        {previewTab === 'thumbnail' && (
                            <>
                                <div style={thumbPreviewStyles.gradient} />
                                <div style={thumbPreviewStyles.box}>
                                    <p style={thumbPreviewStyles.text}>{config.text_overlay.text || "PREVIEW TEXT"}</p>
                                </div>
                            </>
                        )}

                        {/* CAPTION SIMULATION LAYER */}
                        {previewTab === 'caption' && (
                            <div style={capPreviewStyles.container}>
                                <div style={capPreviewStyles.textBox}>
                                    {capPreviewStyles.lines.map((line, lid) => (
                                        <div key={lid}>
                                            {line.map((word, wid) => {
                                                // Mock Highlighting (e.g. 2nd word of 1st line)
                                                const isHighlight = (lid === 0 && wid === 1) || (lid === 1 && wid === 0)
                                                return (
                                                    <span key={wid} style={{
                                                        ...capPreviewStyles.text,
                                                        color: isHighlight ? capConfig.settings.word_color : capConfig.settings.line_color
                                                    }}>
                                                        {word}{' '}
                                                    </span>
                                                )
                                            })}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                </div>

                {/* BOTTOM ACTION BAR */}
                <div className="p-6 pb-8 flex justify-center w-full bg-gradient-to-t from-background to-transparent">
                    <Button
                        size="lg"
                        className="w-full max-w-sm bg-white text-black hover:bg-zinc-200 shadow-[0_0_30px_-5px_rgba(255,255,255,0.3)] transition-all transform hover:scale-105"
                        onClick={handleGenerate}
                        disabled={generateMutation.isPending}
                    >
                        {generateMutation.isPending ? <Loader2 className="mr-2 h-5 w-5 animate-spin" /> : <Sparkles className="mr-2 h-5 w-5 fill-current" />}
                        GENERATE CLIPPER
                    </Button>
                </div>
            </div>


            {/* 3. RIGHT PANEL: THUMBNAIL INSPECTOR (25%) */}
            <div className="w-[380px] border-l border-border bg-card/50 flex flex-col h-full z-10">
                <div className="p-4 border-b border-border bg-card/50">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
                        <LayoutTemplate className="h-3.5 w-3.5" /> Thumbnail Design
                    </h3>
                </div>

                <div className="flex-1 overflow-y-auto p-4 space-y-6 scrollbar-thin scrollbar-thumb-white/10">
                    {/* Reuse existing Thumbnail Controls Logic here but mapped to `config` */}
                    <div className="space-y-4">
                        <Label className="text-xs font-bold text-primary/80 uppercase">Text Overlay</Label>
                        <Input value={config.text_overlay.text} onChange={e => updateThumbRoot(e.target.value)} className="bg-background/50" />

                        <div className="grid grid-cols-2 gap-2 mt-2">
                            <Select value={config.text_overlay.style.font_family} onValueChange={v => updateThumbnail('style', 'font_family', v)}>
                                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="Komika Axis">Komika Axis</SelectItem>
                                    <SelectItem value="Poppins">Poppins</SelectItem>
                                    <SelectItem value="Impact">Impact</SelectItem>
                                </SelectContent>
                            </Select>
                            <Select value={config.text_overlay.style.font_weight} onValueChange={v => updateThumbnail('style', 'font_weight', v)}>
                                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="bold">Bold</SelectItem>
                                    <SelectItem value="regular">Regular</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>

                        <div className="space-y-1 pt-2">
                            <Label className="text-[10px] text-muted-foreground">Size ({config.text_overlay.style.font_size}px)</Label>
                            <Slider value={[config.text_overlay.style.font_size]} min={40} max={300} step={10} onValueChange={([v]) => updateThumbnail('style', 'font_size', v)} />
                        </div>

                        <div className="space-y-2 pt-2">
                            <ColorPicker label="Text Color" color={config.text_overlay.style.color} onChange={c => updateThumbnail('style', 'color', c)} />
                            <ColorPicker label="Stroke" color={config.text_overlay.style.stroke_color} onChange={c => updateThumbnail('style', 'stroke_color', c)} />
                            <ColorPicker label="Shadow" color={config.text_overlay.style.text_shadow.split(' ').pop() || '#000'} onChange={c => updateThumbnail('style', 'text_shadow', `10px 10px 0px ${c} `)} />
                        </div>
                    </div>

                    <div className="h-px bg-border" />

                    <div className="space-y-4">
                        <div className="flex justify-between items-center">
                            <Label className="text-xs font-bold text-primary/80 uppercase">Background</Label>
                            <Switch checked={config.text_overlay.background.enabled} onCheckedChange={c => updateThumbnail('background', 'enabled', c)} />
                        </div>

                        {config.text_overlay.background.enabled && (
                            <div className="space-y-3 pl-2 border-l border-border ml-1">
                                <div className="flex justify-between">
                                    <Label className="text-xs text-muted-foreground">Gradient Mode</Label>
                                    <Switch checked={config.text_overlay.background.gradient} onCheckedChange={c => updateThumbnail('background', 'gradient', c)} className="scale-75" />
                                </div>
                                <ColorPicker label="BG Color" color={config.text_overlay.background.color} supportOpacity onChange={c => updateThumbnail('background', 'color', c)} />
                            </div>
                        )}
                    </div>

                    <div className="h-px bg-border" />

                    <div className="space-y-4">
                        <Label className="text-xs font-bold text-primary/80 uppercase">Position</Label>
                        <Select value={config.text_overlay.position.y} onValueChange={v => updateThumbnail('position', 'y', v)}>
                            <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                            <SelectContent>
                                <SelectItem value="bottom">Bottom</SelectItem>
                                <SelectItem value="center">Center</SelectItem>
                                <SelectItem value="top">Top</SelectItem>
                            </SelectContent>
                        </Select>
                        <div className="space-y-1">
                            <Label className="text-[10px] text-muted-foreground">Margin ({config.text_overlay.position.margin_bottom}px)</Label>
                            <Slider value={[config.text_overlay.position.margin_bottom]} min={0} max={500} step={10} onValueChange={([v]) => updateThumbnail('position', 'margin_bottom', v)} />
                        </div>
                    </div>

                </div>
            </div>

        </div>
    )
}

