import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../core/theme/app_theme.dart';
import '../../../data/models/models.dart';
import '../../../shared/utils/formatters.dart';
import '../../../shared/widgets/loading_view.dart';

/// Phone verification (spec 3).
///
/// When [onboardingToken] is present the user arrived from Google or Telegram
/// and this screen is mandatory — there is deliberately no skip control and no
/// back button, because a session cannot exist without a verified number.
class PhoneAuthScreen extends ConsumerStatefulWidget {
  const PhoneAuthScreen({super.key, this.onboardingToken});

  final String? onboardingToken;

  @override
  ConsumerState<PhoneAuthScreen> createState() => _PhoneAuthScreenState();
}

class _PhoneAuthScreenState extends ConsumerState<PhoneAuthScreen> {
  final TextEditingController _phoneController = TextEditingController();
  final TextEditingController _codeController = TextEditingController();
  final GlobalKey<FormState> _formKey = GlobalKey<FormState>();

  OtpChallenge? _challenge;
  bool _busy = false;
  int _resendSeconds = 0;
  Timer? _timer;

  bool get _isMandatory => widget.onboardingToken != null;

  @override
  void dispose() {
    _timer?.cancel();
    _phoneController.dispose();
    _codeController.dispose();
    super.dispose();
  }

  void _startResendCountdown(DateTime availableAt) {
    _timer?.cancel();
    void tick() {
      final int seconds = availableAt.difference(DateTime.now()).inSeconds;
      if (!mounted) return;
      setState(() => _resendSeconds = seconds > 0 ? seconds : 0);
      if (seconds <= 0) _timer?.cancel();
    }

    tick();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) => tick());
  }

  Future<void> _sendCode() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() => _busy = true);
    try {
      final OtpChallenge challenge =
          await ref.read(authRepositoryProvider).startPhoneAuth(
                Validators.normalizePhone(_phoneController.text),
                ref.read(localeProvider).languageCode,
              );
      setState(() => _challenge = challenge);
      _startResendCountdown(challenge.resendAvailableAt);

      // Outside production the API returns the code so testing needs no SMS.
      if (challenge.debugCode != null) {
        _codeController.text = challenge.debugCode!;
      }
    } catch (error) {
      if (mounted) showApiError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _verify() async {
    final OtpChallenge? challenge = _challenge;
    if (challenge == null || _codeController.text.trim().length < 4) return;

    setState(() => _busy = true);
    try {
      final SessionResponse response = await ref.read(authRepositoryProvider).verifyPhone(
            challengeId: challenge.challengeId,
            code: _codeController.text.trim(),
            onboardingToken: widget.onboardingToken,
          );
      await ref.read(sessionProvider.notifier).applySession(response);

      // The root gate takes over from here; pop the screen if it was pushed.
      if (mounted && Navigator.of(context).canPop()) {
        Navigator.of(context).pop();
      }
    } catch (error) {
      if (mounted) showApiError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;
    final ThemeData theme = Theme.of(context);
    final bool codeStage = _challenge != null;

    return Scaffold(
      appBar: AppBar(
        automaticallyImplyLeading: !_isMandatory,
        title: Text(
          l10n.t(codeStage ? 'auth.code_title' : 'auth.phone_title'),
        ),
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(AppSpacing.xl),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: <Widget>[
                if (_isMandatory)
                  Container(
                    margin: const EdgeInsets.only(bottom: AppSpacing.xl),
                    padding: const EdgeInsets.all(AppSpacing.lg),
                    decoration: BoxDecoration(
                      color: AppColors.primaryLight,
                      borderRadius: BorderRadius.circular(AppSpacing.radiusMd),
                    ),
                    child: Row(
                      children: <Widget>[
                        const Icon(
                          Icons.shield_outlined,
                          color: AppColors.primaryDark,
                        ),
                        const SizedBox(width: AppSpacing.md),
                        Expanded(
                          child: Text(
                            l10n.t('auth.phone_required_notice'),
                            style: const TextStyle(
                              color: AppColors.primaryDark,
                              fontSize: 13.5,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                Text(
                  codeStage
                      ? l10n.tp('auth.code_sent', <String, Object?>{
                          'phone': Formatters.phone(
                            Validators.normalizePhone(_phoneController.text),
                          ),
                        })
                      : l10n.t('auth.phone_hint'),
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: AppColors.textSecondary,
                  ),
                ),
                const SizedBox(height: AppSpacing.xl),
                if (!codeStage) ...<Widget>[
                  TextFormField(
                    controller: _phoneController,
                    keyboardType: TextInputType.phone,
                    autofocus: true,
                    inputFormatters: <TextInputFormatter>[
                      FilteringTextInputFormatter.allow(RegExp(r'[\d+\s()-]')),
                    ],
                    decoration: InputDecoration(
                      labelText: l10n.t('auth.phone_label'),
                      hintText: '+998 90 123 45 67',
                      prefixIcon: const Icon(Icons.phone_rounded),
                    ),
                    validator: (String? value) => Validators.phone(
                      value,
                      l10n.t('error.invalid_phone'),
                    ),
                  ),
                  const SizedBox(height: AppSpacing.xl),
                  FilledButton(
                    onPressed: _busy ? null : _sendCode,
                    child:
                        _busy ? const _ButtonSpinner() : Text(l10n.t('auth.send_code')),
                  ),
                ] else ...<Widget>[
                  TextFormField(
                    controller: _codeController,
                    keyboardType: TextInputType.number,
                    autofocus: true,
                    maxLength: 6,
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      fontSize: 28,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 10,
                    ),
                    inputFormatters: <TextInputFormatter>[
                      FilteringTextInputFormatter.digitsOnly,
                    ],
                    decoration: InputDecoration(
                      counterText: '',
                      labelText: l10n.t('auth.code_label'),
                    ),
                    onChanged: (String value) {
                      // Submit as soon as the full code is entered.
                      if (value.length == 6 && !_busy) _verify();
                    },
                  ),
                  const SizedBox(height: AppSpacing.xl),
                  FilledButton(
                    onPressed: _busy ? null : _verify,
                    child: _busy ? const _ButtonSpinner() : Text(l10n.t('auth.verify')),
                  ),
                  const SizedBox(height: AppSpacing.md),
                  TextButton(
                    onPressed: _resendSeconds > 0 || _busy
                        ? null
                        : () {
                            setState(() => _challenge = null);
                            _sendCode();
                          },
                    child: Text(
                      _resendSeconds > 0
                          ? l10n.tp('auth.resend_in', <String, Object?>{
                              'seconds': _resendSeconds,
                            })
                          : l10n.t('auth.resend'),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ButtonSpinner extends StatelessWidget {
  const _ButtonSpinner();

  @override
  Widget build(BuildContext context) {
    return const SizedBox(
      width: 20,
      height: 20,
      child: CircularProgressIndicator(strokeWidth: 2.2, color: Colors.white),
    );
  }
}
