@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem The four app dev servers are started directly through pnpm instead of
rem `turbo run dev`. Turborepo cannot parse packages\propel-ui\package.json in
rem this checkout and its `dev` graph also runs a second tsdown writer against
rem the same dist folder. See WORK LEDGER.md entries 22-25.

if not exist "packages\propel-ui\dist\accordion\index.js" (
    echo Building workspace packages...
    call pnpm -r --filter "./packages/*" run build
    if errorlevel 1 goto fail
)

echo.
echo web    http://localhost:3000
echo admin  http://localhost:3001/god-mode
echo space  http://localhost:3002/spaces
echo live   http://localhost:3100/live/health
echo.

rem --no-bail: one app crashing (for example live when editor/dist is missing)
rem must not take the other three down with it.
call pnpm --parallel --no-bail --filter "./apps/web" --filter "./apps/admin" --filter "./apps/space" --filter "./apps/live" run dev
goto :eof

:fail
echo.
echo Frontend build failed.
pause
exit /b 1
