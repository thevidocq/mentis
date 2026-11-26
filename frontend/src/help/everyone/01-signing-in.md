# Signing in and two-factor authentication

Mentis always asks for two things: your password and a 6-digit code from an authenticator app.

## First sign-in

1. Open the invitation link from your email (or the one your admin sent you) and set your password.
2. Go to the sign-in page and enter your email and password.
3. Scan the QR code with an authenticator app: Microsoft Authenticator, Google Authenticator, 1Password or similar. If you cannot scan it, type the key shown under the code.
4. Enter the 6-digit code the app shows and select **Activate and sign in**.

## Every other sign-in

Enter email and password, then the current 6-digit code from the app. Codes change every 30 seconds.

## Forgot your password

1. On the sign-in page select **Forgot password?** and enter your email.
2. Open the link you receive (valid 60 minutes, once) and choose a new password.
3. Sign in with the new password and the code from your authenticator app: the app is still required.

Every open session is closed when the password changes. If no email arrives (email not configured), ask an admin: they can create a reset link from **Users** and send it to you.

## Password rules

- At least 12 characters
- Upper and lower case letters
- At least one digit
- At most 256 characters

## Sessions

A session lasts 12 hours. Changing your password signs out all your other sessions.

> Invitation links work once and expire after 72 hours. If yours has expired, ask your admin for a new one.
