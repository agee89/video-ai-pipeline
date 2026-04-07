import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import StudioLayout from "@/layouts/StudioLayout"
import ThumbnailGenerator from "@/pages/ThumbnailGenerator"
import { ThemeProvider } from "@/components/theme-provider"

const queryClient = new QueryClient()

function App() {
  return (
    <ThemeProvider defaultTheme="dark" storageKey="vite-ui-theme">
      <QueryClientProvider client={queryClient}>
        <StudioLayout>
          <ThumbnailGenerator />
        </StudioLayout>
      </QueryClientProvider>
    </ThemeProvider>
  )
}

export default App
