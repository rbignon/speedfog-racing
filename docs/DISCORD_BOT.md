# Discord Bot Setup

This guide covers configuring the Discord bot integration for SpeedFog Racing. The bot provides:

- **Race notifications** with `@Runner` role mention
- **Scheduled events** synced with the race lifecycle
- **Self-service Runner role** via button interactions

All features are optional and degrade gracefully — if a setting is missing, the corresponding feature is silently skipped.

## 1. Create a Discord Application

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application**, name it (e.g. "SpeedFog Racing")
3. Note the **Application ID** and **Public Key** from the General Information page

## 2. Create a Bot

1. Go to the **Bot** tab
2. Click **Reset Token** and copy the token — this is your `DISCORD_BOT_TOKEN`
3. Under **Privileged Gateway Intents**, no special intents are required

## 3. Invite the Bot to Your Server

Generate an invite URL with these permissions:

- **Manage Roles** — assign/remove the Runner role
- **Manage Events** — update/delete scheduled events
- **Create Events** — create scheduled events
- **Send Messages** — post the Runner button message

Use this URL template (replace `APPLICATION_ID`):

```
https://discord.com/oauth2/authorize?client_id=APPLICATION_ID&permissions=17601044416512&scope=bot
```

Permission integer `17601044416512` = Manage Roles (1<<28) + Manage Events (1<<33) + Create Events (1<<44) + Send Messages (1<<11).

## 4. Create the Runner Role

1. In your Discord server, go to **Server Settings > Roles**
2. Create a role named **Runner** (or whatever you prefer)
3. Move the role **below** the bot's role in the hierarchy (the bot can only assign roles below its own)
4. Copy the role ID — this is your `DISCORD_RUNNER_ROLE_ID`

To copy a role ID: enable Developer Mode in Discord settings (App Settings > Advanced), then right-click the role and select "Copy Role ID".

## 5. Get the Channel and Guild IDs

- **Guild ID** (`DISCORD_GUILD_ID`): Right-click the server name > Copy Server ID
- **Channel ID** (`DISCORD_CHANNEL_ID`): Right-click the channel where you want the Runner button message > Copy Channel ID

## 6. Set the Interaction Endpoint

1. In the Discord Developer Portal, go to your application's **General Information** page
2. Set **Interactions Endpoint URL** to:

   ```
   https://your-domain.com/api/discord/interactions
   ```

3. Discord will send a PING to verify the endpoint — the server must be running and reachable

## 7. Environment Variables

Add these to your `server/.env`:

```bash
# Discord webhook (race notifications in a channel)
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Discord bot (scheduled events, runner role, interactions)
DISCORD_BOT_TOKEN=your-bot-token
DISCORD_GUILD_ID=123456789012345678
DISCORD_RUNNER_ROLE_ID=123456789012345678
DISCORD_PUBLIC_KEY=your-app-public-key-hex
DISCORD_CHANNEL_ID=123456789012345678

# Used for race URLs in notifications and scheduled events
BASE_URL=https://your-domain.com
```

| Variable                 | Required for    | Description                                                       |
| ------------------------ | --------------- | ----------------------------------------------------------------- |
| `DISCORD_WEBHOOK_URL`    | Notifications   | Webhook URL for race create/start/finish embeds                   |
| `DISCORD_BOT_TOKEN`      | Bot API calls   | Bot token from Developer Portal                                   |
| `DISCORD_GUILD_ID`       | Events + roles  | Your Discord server ID                                            |
| `DISCORD_RUNNER_ROLE_ID` | Role management | The Runner role ID to assign/remove                               |
| `DISCORD_PUBLIC_KEY`     | Interactions    | Ed25519 public key for signature verification                     |
| `DISCORD_CHANNEL_ID`     | Runner message  | Channel for the Runner button message                             |
| `BASE_URL`               | URLs            | Base URL for race links (default: `https://speedfog.malenia.win`) |

## 8. Post the Runner Button Message

Once the bot is running and configured, an admin can post the button message:

```bash
curl -X POST https://your-domain.com/api/discord/setup-runner-message \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

This posts a message with two buttons ("Become a Runner" / "Remove Runner") in the configured channel. Users click these to self-assign or remove the Runner role.

## Feature Details

### Race Notifications (Webhook)

When `DISCORD_WEBHOOK_URL` is set, race lifecycle events post embeds:

- **Race created** — with pool, organizer, schedule info. Mentions `@Runner` if `DISCORD_RUNNER_ROLE_ID` is set.
- **Race started** — with participant count
- **Race finished** — with podium (top 3 times)

### Scheduled Events (Bot)

When `DISCORD_BOT_TOKEN` and `DISCORD_GUILD_ID` are set, public races with a scheduled time automatically create Discord scheduled events:

| Race action                    | Discord event                        |
| ------------------------------ | ------------------------------------ |
| Create (public + scheduled)    | Create EXTERNAL event (duration: 3h) |
| Update scheduled time          | Update event time                    |
| Clear schedule or make private | Delete event                         |
| Start race                     | Set event ACTIVE                     |
| Finish race                    | Set event COMPLETED                  |
| Delete race                    | Delete event                         |

Events link to the race page URL.

### Runner Role (Bot)

When `DISCORD_GUILD_ID` and `DISCORD_RUNNER_ROLE_ID` are set:

- The Runner button message lets users self-assign/remove the role
- Race creation notifications mention `@Runner` to ping interested players

## Troubleshooting

**Interaction endpoint verification fails:**

- Ensure the server is publicly reachable at the configured URL
- Check that `DISCORD_PUBLIC_KEY` matches the value in the Developer Portal
- Check server logs for signature verification errors

**Bot can't assign roles:**

- The bot's role must be **higher** than the Runner role in the server's role hierarchy
- Verify the bot has "Manage Roles" permission

**Scheduled events not appearing:**

- Check that `DISCORD_BOT_TOKEN` and `DISCORD_GUILD_ID` are set
- The race must be **public** and have a **scheduled_at** time
- Check server logs for Discord API errors

**Webhook notifications not posting:**

- Verify `DISCORD_WEBHOOK_URL` is a valid webhook URL
- Test the webhook directly: `curl -X POST YOUR_WEBHOOK_URL -H "Content-Type: application/json" -d '{"content": "test"}'`
