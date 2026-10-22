# VAYR VPN public download page — setup checklist

The website draft is in `docs/` on branch `vayr-download-page` of `Ellai95/apple-ipa-files`. It is not live until assets are uploaded, the branch is reviewed/merged, and GitHub Pages is enabled.

## Required public release assets

Add the following exact names to the public GitHub Release tagged `vayr-vpn` (or update the links in `docs/index.html` if using another tag):

- `VAYR-Android.apk` — only after setting up and preserving an owner-controlled release signing key. Do not use a debug/test key for the long-term public release.
- `VAYR-Android-TV.apk` — publish only after testing the current TV build.
- `VAYR-Windows-Setup.exe` — Windows installer.
- `VAYR-Windows-Portable.zip` — complete portable folder, not an EXE renamed to ZIP.
- The current iOS asset already exists as `VAYR-0.4.2-37216dfd.ipa`.

Add `SHA256SUMS.txt` and list checksums in the release notes. Never publish private signing keys, provisioning secrets, tokens or the Android keystore.

## Enable GitHub Pages

1. Review and merge this branch into `main`.
2. Open repository **Settings → Pages**.
3. Select **Deploy from a branch**, branch `main`, folder `/docs`, then Save.
4. Copy the final Pages URL shown in Settings → Pages and test it on a phone and a computer.
5. Test every download link after uploading the exact assets above. The Android and Windows links will return 404 until those files exist in the public release.

## Release and legal checks

- Android CI currently creates development/test-signed builds. Generate a dedicated release keystore, keep an offline backup and configure the build to use it; future APK updates must use the same signing identity.
- The current Windows build has no publisher certificate. Publish SHA-256 and tell users not to disable Defender/SmartScreen.
- Do not mix an older TV APK with the latest phone build without testing it on Android TV.
- The iOS IPA may require re-signing with a compatible certificate and provisioning profile. Do not promise fixed certificate lifetime or guaranteed availability.
- State clearly that the app download is free but the VAYR VPN service requires a personal access key.
- Russian law restricts advertising of software/hardware used to access resources whose access is restricted; FAS has also published guidance about ads on restricted platforms. Before prominently promoting VAYR VPN or certificate sales to Russian audiences, obtain current legal review. Do not disguise advertising as technical documentation.
- The Apple IPA Store and certificate-support blocks are included as draft cross-promotion. Review them against local rules before making the page public in Russia.

## Files

- `docs/index.html` — bilingual RU/EN download page.
- `docs/privacy.html` — website-only privacy notice, not the VPN app's privacy policy.
