# Cogi's 20-second demo: Claude forgets, Cogi doesn't. A real Claude Code session, typed by VHS.
#
#   brew install vhs
#   vhs scripts/demo/acorn.tape        # from the repository root
#
# Writes site/assets/cogi-demo.gif (README, docs site) and site/assets/cogi-demo.mp4 (LinkedIn, X).
# Needs Claude Code logged in, with the cogito-mem plugin installed and its model downloaded (`/mcp`
# shows cogi connected). It runs in a new folder, ~/cogi-demo, so no other session's memory shows up
# first. If Claude takes longer to answer, raise the two long Sleeps; if your Claude Code uses its
# light theme, use "Catppuccin Latte".

Output site/assets/cogi-demo.gif
Output site/assets/cogi-demo.mp4

Require claude

Set Shell "bash"
Set FontSize 20
Set Width 1200
Set Height 640
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms
Set PlaybackSpeed 1.5

Hide
Type "mkdir -p ~/cogi-demo && cd ~/cogi-demo && clear && claude"
Enter
Sleep 5s
# a new folder asks whether to trust it: Enter takes the default, yes (and does nothing otherwise)
Enter
Sleep 2s
Show

Type `Let's call the staging server "acorn".`
Sleep 500ms
Enter
Sleep 10s

Type "/clear"
Sleep 300ms
Enter
Sleep 2s

Type "What did we call the staging server?"
Sleep 500ms
Enter
Sleep 11s
Sleep 4s

Hide
Ctrl+C
Ctrl+C
