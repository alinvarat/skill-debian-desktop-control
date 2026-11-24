# Discord Developer Portal via desktop control

Use with the input-action rules in SKILL.md. Each step ends with a fresh capture; do not chain clicks across a save or a reset.

## Flow
1. Applications page → New Application → name it → accept the captcha/verification handoff yourself if it appears. Re-check the app list before any retry (duplicate apps appear if Create is clicked twice).
2. Bot tab: the bot user is created with the app. The username field is editable there; the avatar upload area is optional.
3. Privileged Gateway Intents: turn on **Message Content Intent** if the bot must read ordinary channel messages. Toggling does nothing until the bottom bar's green save button is pressed; confirm the success banner.
4. Token: the Reset Token confirmation dialog states the consequence; the user approves the reset. Copy the token via the Copy control, then read it with `wl-paste -n` (see the token-reveal pitfall in SKILL.md). Never print it.
5. Bot Permissions for the invite: the permission integer comes from the planned role. For a basic text bot with read/send/embeds/history plus add-reactions, `101376` is the integer used in the invite URL.
6. Invite URL: `https://discord.com/oauth2/authorize?client_id=<APP_ID>&scope=bot&permissions=<INT>&guild_id=<GUILD_ID>`. Open it in the user's own Chrome window (`xdg-open` only the first time; afterwards resume the same tab). The user clicks Authorize; the agent does not click the consent button on the user's behalf unless the card was answered yes for that page.
7. Confirm the join through the REST API instead of the screen: `GET /guilds/<GUILD_ID>/members/<BOT_ID>` with the bot token returns 200 once the bot is in. Poll every few seconds for a bounded period, then report if it never joins.

## Config after join (profile-level)
- Set the bot's behaviour with the profile's own config (`discord.require_mention`, `discord.allow_bots`, `discord.auto_thread`) rather than editing the file by hand. Keep auto-thread off for a plain channel bot unless the user asks for threads.
- Create the target channel through the REST API (`POST /guilds/<id>/channels`) when a dedicated room is needed; it is faster and less error-prone than the GUI.

## Pitfalls
- A single-pixel miss on a Discord toggle silently flips a neighbour option; re-capture before saving.
- The developer portal reflows after an edit: coordinates captured before a save are stale. Take a fresh capture first.
- Discord may show an alert such as `Discord has detected...` on new apps; read it and hand verification steps to the user.