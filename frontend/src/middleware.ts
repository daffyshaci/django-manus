import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server'

// Treat proxied API routes as public so Clerk won't try to protect/redirect them
const isProxiedApi = createRouteMatcher([
  '/v1(.*)',
  '/openapi.json',
])

export default clerkMiddleware((auth, req) => {
  if (isProxiedApi(req)) {
    // Allow through without any auth handling
    return
  }
  // Note: We are not calling auth().protect() here to keep existing behavior.
})

export const config = {
  matcher: [
    // Skip Next.js internals and all static files, unless found in search params
    '/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)',
    // Always run for API routes
    '/(api|trpc)(.*)',
  ],
}
