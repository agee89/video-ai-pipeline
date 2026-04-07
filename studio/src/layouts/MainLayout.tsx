import { useState } from "react"
import { MonitorPlay, LayoutTemplate, MessageSquareText, Settings, Menu } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"

export default function Layout({ children }: { children: React.ReactNode }) {
    const [sidebarOpen, setSidebarOpen] = useState(true)

    return (
        <div className="flex h-screen bg-background text-foreground overflow-hidden">
            {/* Sidebar */}
            <aside
                className={cn(
                    "bg-card border-r transition-all duration-300 ease-in-out flex flex-col",
                    sidebarOpen ? "w-64" : "w-16"
                )}
            >
                <div className="h-16 flex items-center px-4 border-b">
                    <MonitorPlay className="h-8 w-8 text-primary shrink-0" />
                    <span
                        className={cn(
                            "ml-3 font-bold text-lg whitespace-nowrap overflow-hidden transition-all duration-300",
                            sidebarOpen ? "opacity-100" : "opacity-0 w-0"
                        )}
                    >
                        Video AI Studio
                    </span>
                </div>

                <div className="flex-1 py-4 flex flex-col gap-2">
                    <NavButton icon={<LayoutTemplate />} label="Thumbnails" active />
                    <NavButton icon={<MessageSquareText />} label="Captions" />
                    <NavButton icon={<MonitorPlay />} label="Clips" />
                </div>

                <div className="p-4 border-t">
                    <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setSidebarOpen(!sidebarOpen)}
                        className="w-full justify-start"
                    >
                        <Menu className="h-5 w-5" />
                    </Button>
                </div>
            </aside>

            {/* Main Content */}
            <main className="flex-1 overflow-auto bg-neutral-50 dark:bg-neutral-900 p-8">
                <div className="max-w-7xl mx-auto">{children}</div>
            </main>
        </div>
    )
}

function NavButton({
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
        <Button
            variant={active ? "secondary" : "ghost"}
            className={cn("w-full justify-start px-4 mb-1", active && "bg-secondary")}
            onClick={onClick}
        >
            {icon}
            <span className="ml-3 truncate">{label}</span>
        </Button>
    )
}
