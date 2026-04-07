import { MonitorPlay, LayoutTemplate, MessageSquareText, Settings, Video, Layers, Wand2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"

import { ModeToggle } from "@/components/mode-toggle"

export default function StudioLayout({ children }: { children: React.ReactNode }) {
    return (
        <div className="flex h-screen bg-background text-foreground overflow-hidden font-sans transition-colors duration-300">
            {/* Sleek Sidebar */}
            <aside className="w-[70px] flex flex-col items-center py-6 border-r border-border/40 bg-card/50 backdrop-blur-xl z-50 transition-colors duration-300">
                <div className="mb-8 p-2 rounded-xl bg-primary/10 text-primary">
                    <MonitorPlay className="h-6 w-6" />
                </div>

                <nav className="flex-1 flex flex-col gap-4 w-full px-2">
                    <NavIcon icon={<LayoutTemplate />} label="Thumbnails" active />
                    <NavIcon icon={<MessageSquareText />} label="Captions" />
                    <NavIcon icon={<Video />} label="Clips" />
                    <div className="h-px bg-border/40 w-8 mx-auto my-2" />
                    <NavIcon icon={<Layers />} label="Assets" />
                    <NavIcon icon={<Wand2 />} label="AI Tools" />
                </nav>

                <div className="mt-auto flex flex-col gap-4 px-2 items-center">
                    <ModeToggle />
                    <NavIcon icon={<Settings />} label="Settings" />
                </div>
            </aside>

            {/* Main Workspace */}
            <main className="flex-1 flex flex-col overflow-hidden relative">
                {/* Ambient Glow */}
                <div className="absolute top-[-20%] right-[-10%] w-[800px] h-[800px] bg-purple-500/10 rounded-full blur-[120px] pointer-events-none" />
                <div className="absolute bottom-[-20%] left-[-10%] w-[600px] h-[600px] bg-indigo-500/10 rounded-full blur-[100px] pointer-events-none" />

                <div className="flex-1 overflow-auto z-10">
                    {children}
                </div>
            </main>
        </div>
    )
}

function NavIcon({
    icon,
    label,
    active = false,
    onClick,
}: {
    icon: React.ReactNode
    label: string
    active?: boolean
    onClick?: () => void
}) {
    return (
        <div className="group relative flex items-center justify-center">
            <Button
                variant="ghost"
                size="icon"
                className={cn(
                    "h-10 w-10 rounded-xl transition-all duration-300",
                    active
                        ? "bg-primary text-primary-foreground shadow-[0_0_15px_rgba(255,255,255,0.15)] scale-105"
                        : "text-muted-foreground hover:text-foreground hover:bg-accent"
                )}
                onClick={onClick}
            >
                {icon}
            </Button>

            {/* Tooltip on hover */}
            <div className="absolute left-14 px-2 py-1 bg-popover border border-border text-popover-foreground text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none select-none z-50 shadow-xl">
                {label}
            </div>
        </div>
    )
}
