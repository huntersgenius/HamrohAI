import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/config/env.dart';
import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../core/theme/app_theme.dart';
import '../../../data/models/models.dart';
import '../../../shared/widgets/common_widgets.dart';
import '../../../shared/widgets/loading_view.dart';
import 'phone_auth_screen.dart';

/// Sign-in entry point (spec 3).
///
/// All three routes converge on the same place: phone verification. Google and
/// Telegram only prove control of an external account; the platform identity is
/// always the verified phone number.
class WelcomeScreen extends ConsumerStatefulWidget {
  const WelcomeScreen({super.key});

  @override
  ConsumerState<WelcomeScreen> createState() => _WelcomeScreenState();
}

class _WelcomeScreenState extends ConsumerState<WelcomeScreen> {
  bool _busy = false;

  Future<void> _signInWithGoogle() async {
    setState(() => _busy = true);
    try {
      final GoogleSignIn googleSignIn = GoogleSignIn(
        scopes: <String>['email', 'profile'],
        serverClientId:
            Env.googleServerClientId.isEmpty ? null : Env.googleServerClientId,
      );
      // Sign out first so the account chooser always appears; a shared phone is
      // common here and silently reusing the last account is a real hazard.
      await googleSignIn.signOut();

      final GoogleSignInAccount? account = await googleSignIn.signIn();
      if (account == null) return;

      final GoogleSignInAuthentication auth = await account.authentication;
      final String? idToken = auth.idToken;
      if (idToken == null) {
        if (mounted) showApiError(context, 'no_id_token');
        return;
      }

      final SessionResponse response = await ref
          .read(authRepositoryProvider)
          .signInWithGoogle(idToken, ref.read(localeProvider).languageCode);
      await ref.read(sessionProvider.notifier).applySession(response);
    } catch (error) {
      if (mounted) showApiError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _signInWithTelegram() async {
    // The bot deep-link hands the signed payload back to the app; until the
    // user completes it there, phone sign-in remains available.
    final Uri uri = Uri.parse('https://t.me/${Env.telegramBotName}?start=login');
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    } else if (mounted) {
      showApiError(context, 'cannot_open_telegram');
    }
  }

  void _continueWithPhone() {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (BuildContext context) => const PhoneAuthScreen(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;
    final ThemeData theme = Theme.of(context);

    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xl),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Align(
                alignment: Alignment.topRight,
                child: LanguagePicker(
                  onSelected: (String code) =>
                      ref.read(localeProvider.notifier).set(code),
                ),
              ),
              const Spacer(),
              Container(
                width: 84,
                height: 84,
                decoration: BoxDecoration(
                  color: AppColors.primary,
                  borderRadius: BorderRadius.circular(AppSpacing.radiusXl),
                ),
                child: const Icon(
                  Icons.favorite_rounded,
                  color: Colors.white,
                  size: 44,
                ),
              ),
              const SizedBox(height: AppSpacing.xl),
              Text(
                l10n.t('auth.welcome_title'),
                style: theme.textTheme.headlineSmall?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: AppSpacing.sm),
              Text(
                l10n.t('auth.welcome_subtitle'),
                style: theme.textTheme.bodyLarge?.copyWith(
                  color: AppColors.textSecondary,
                ),
              ),
              const Spacer(),
              if (_busy)
                const Padding(
                  padding: EdgeInsets.only(bottom: AppSpacing.lg),
                  child: LinearProgressIndicator(minHeight: 3),
                ),
              OutlinedButton.icon(
                onPressed: _busy ? null : _signInWithGoogle,
                icon: const Icon(Icons.account_circle_outlined),
                label: Text(l10n.t('auth.google')),
              ),
              const SizedBox(height: AppSpacing.md),
              OutlinedButton.icon(
                onPressed: _busy ? null : _signInWithTelegram,
                icon: const Icon(Icons.send_rounded),
                label: Text(l10n.t('auth.telegram')),
              ),
              const SizedBox(height: AppSpacing.md),
              FilledButton.icon(
                onPressed: _busy ? null : _continueWithPhone,
                icon: const Icon(Icons.phone_rounded),
                label: Text(l10n.t('auth.phone')),
              ),
              const SizedBox(height: AppSpacing.xl),
            ],
          ),
        ),
      ),
    );
  }
}
