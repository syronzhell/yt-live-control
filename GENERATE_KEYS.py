"""Run on your own device. Generated values are private; never upload them to GitHub."""
import secrets
print('Copy these into Vercel Environment Variables; keep them private.\n')
print('CMS_PASSWORD=' + secrets.token_urlsafe(18))
print('SESSION_SECRET=' + secrets.token_urlsafe(48))
print('AGENT_KEY=' + secrets.token_urlsafe(48))
print('\nUse the SAME AGENT_KEY in the Windows/RDP pairing panel.')
input('\nPress Enter to close...')
