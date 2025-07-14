import nodriver as uc
import asyncio

async def get_session_token(max_wait=30):
    browser = None
    try:
        browser = await uc.start(headless=False)
        page = await browser.get("https://spotidownloader.com/")
        
        await page.evaluate("""
            window.originalFetch = window.fetch;
            window.sessionToken = null;
            window.fetch = function(...args) {
                return window.originalFetch(...args).then(async response => {
                    if (response.url.includes('api.spotidownloader.com/session')) {
                        try {
                            const data = await response.clone().json();
                            if (data?.token) window.sessionToken = data.token;
                        } catch {}
                    }
                    return response;
                });
            };        
        """)
        
        await page.evaluate('document.querySelector("button.flex.justify-center.items-center.bg-button")?.click()')
        
        for _ in range(max_wait * 2):
            token = await page.evaluate("window.sessionToken")
            if token:
                return token
            await asyncio.sleep(0.5)
        
        return None
    except:
        return None
    finally:
        if browser:
            try:
                await browser.stop()
            except:
                pass

async def main():
    token = await get_session_token()
    if token:
        print(token)
    return token

if __name__ == "__main__":
    uc.loop().run_until_complete(main())