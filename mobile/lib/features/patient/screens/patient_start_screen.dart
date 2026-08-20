import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../core/theme/app_theme.dart';
import '../../../data/models/models.dart';
import '../../../shared/utils/formatters.dart';
import '../../../shared/widgets/loading_view.dart';

/// "Doktor kodim bor" vs "Mustaqil ro'yxatdan o'taman" (spec 5.1).
class PatientStartScreen extends ConsumerWidget {
  const PatientStartScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppLocalizations l10n = context.l10n;
    final ThemeData theme = Theme.of(context);

    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xl),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              const SizedBox(height: AppSpacing.xxl),
              Text(
                l10n.t('patient.start_title'),
                style: theme.textTheme.headlineSmall?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: AppSpacing.xxl),
              _OptionCard(
                icon: Icons.qr_code_rounded,
                title: l10n.t('patient.have_code'),
                description: l10n.t('patient.have_code_desc'),
                highlighted: true,
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) => const ConnectCodeScreen(isOnboarding: true),
                  ),
                ),
              ),
              const SizedBox(height: AppSpacing.lg),
              _OptionCard(
                icon: Icons.edit_note_rounded,
                title: l10n.t('patient.self_register'),
                description: l10n.t('patient.self_register_desc'),
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) => const SelfRegisterScreen(),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _OptionCard extends StatelessWidget {
  const _OptionCard({
    required this.icon,
    required this.title,
    required this.description,
    required this.onTap,
    this.highlighted = false,
  });

  final IconData icon;
  final String title;
  final String description;
  final VoidCallback onTap;
  final bool highlighted;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Material(
      color: highlighted ? AppColors.primaryLight : theme.cardTheme.color,
      borderRadius: BorderRadius.circular(AppSpacing.radiusLg),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppSpacing.radiusLg),
        child: Container(
          padding: const EdgeInsets.all(AppSpacing.xl),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(AppSpacing.radiusLg),
            border: Border.all(
              color: highlighted ? AppColors.primary : theme.dividerColor,
              width: highlighted ? 1.5 : 1,
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Icon(icon, size: 30, color: AppColors.primaryDark),
              const SizedBox(height: AppSpacing.md),
              Text(
                title,
                style: theme.textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                description,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: AppColors.textSecondary,
                  height: 1.35,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Enter a doctor's code (spec 5.1 / 5.2 tab 2 "+ Yangi doktor").
class ConnectCodeScreen extends ConsumerStatefulWidget {
  const ConnectCodeScreen({super.key, this.isOnboarding = false});

  /// During onboarding the redeemed invite pre-fills the patient's data.
  final bool isOnboarding;

  @override
  ConsumerState<ConnectCodeScreen> createState() => _ConnectCodeScreenState();
}

class _ConnectCodeScreenState extends ConsumerState<ConnectCodeScreen> {
  final TextEditingController _code = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  Future<void> _connect() async {
    if (_code.text.trim().length < 4) return;
    setState(() => _busy = true);
    try {
      final Map<String, dynamic> response = await ref
          .read(threadRepositoryProvider)
          .connect(_code.text.trim().toUpperCase());

      final bool prefilled = response['prefilled'] == true;
      final String? diagnosis = response['prefilled_diagnosis'] as String?;

      ref.invalidate(threadsProvider);
      if (!mounted) return;

      if (widget.isOnboarding) {
        // The doctor already entered the clinical data; the patient only
        // confirms it (spec 5.1).
        await Navigator.of(context).pushReplacement(
          MaterialPageRoute<void>(
            builder: (_) => _ConfirmPrefilledScreen(
              diagnosis: prefilled ? diagnosis : null,
            ),
          ),
        );
      } else {
        showSuccess(context, context.l10n.t('common.done'));
        Navigator.of(context).pop(true);
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

    return Scaffold(
      appBar: AppBar(title: Text(l10n.t('patient.enter_code'))),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xl),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Text(
                l10n.t('patient.add_doctor_hint'),
                style: const TextStyle(color: AppColors.textSecondary),
              ),
              const SizedBox(height: AppSpacing.xl),
              TextField(
                controller: _code,
                autofocus: true,
                textCapitalization: TextCapitalization.characters,
                textAlign: TextAlign.center,
                maxLength: 10,
                style: const TextStyle(
                  fontSize: 26,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 6,
                ),
                decoration: InputDecoration(
                  counterText: '',
                  labelText: l10n.t('patient.code_label'),
                ),
              ),
              const SizedBox(height: AppSpacing.xl),
              FilledButton(
                onPressed: _busy ? null : _connect,
                child: _busy
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(
                          strokeWidth: 2.2,
                          color: Colors.white,
                        ),
                      )
                    : Text(l10n.t('common.confirm')),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// "Tasdiqlash va davom etish" — review what the doctor pre-filled.
class _ConfirmPrefilledScreen extends ConsumerStatefulWidget {
  const _ConfirmPrefilledScreen({this.diagnosis});

  final String? diagnosis;

  @override
  ConsumerState<_ConfirmPrefilledScreen> createState() => _ConfirmPrefilledScreenState();
}

class _ConfirmPrefilledScreenState extends ConsumerState<_ConfirmPrefilledScreen> {
  bool _busy = false;

  Future<void> _confirm() async {
    setState(() => _busy = true);
    try {
      final AppUser? user = ref.read(sessionProvider).user;
      await ref.read(patientRepositoryProvider).register(
            fullName: user?.fullName ?? '',
          );
      await ref.read(sessionProvider.notifier).refresh();
    } catch (error) {
      if (mounted) showApiError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;
    final AppUser? user = ref.watch(sessionProvider).user;

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.t('patient.confirm_data')),
        automaticallyImplyLeading: false,
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xl),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              const Icon(
                Icons.check_circle_rounded,
                size: 56,
                color: AppColors.ok,
              ),
              const SizedBox(height: AppSpacing.xl),
              _Field(
                label: l10n.t('patient.your_name'),
                value: user?.fullName ?? '',
              ),
              _Field(
                label: l10n.t('auth.phone_label'),
                value: Formatters.phone(user?.phone ?? ''),
              ),
              if (widget.diagnosis != null)
                _Field(
                  label: l10n.t('doctor.diagnosis'),
                  value: widget.diagnosis!,
                ),
              const Spacer(),
              FilledButton(
                onPressed: _busy ? null : _confirm,
                child: Text(l10n.t('patient.confirm_and_continue')),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Field extends StatelessWidget {
  const _Field({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            label,
            style: const TextStyle(
              fontSize: 12,
              color: AppColors.textTertiary,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 3),
          Text(
            value,
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
          ),
        ],
      ),
    );
  }
}

/// Step-by-step self-registration (spec 5.1).
class SelfRegisterScreen extends ConsumerStatefulWidget {
  const SelfRegisterScreen({super.key});

  @override
  ConsumerState<SelfRegisterScreen> createState() => _SelfRegisterScreenState();
}

class _SelfRegisterScreenState extends ConsumerState<SelfRegisterScreen> {
  final PageController _pageController = PageController();
  final TextEditingController _name = TextEditingController();
  final TextEditingController _diagnosis = TextEditingController();
  DateTime? _birthDate;
  String? _gender;
  int _step = 0;
  bool _busy = false;

  @override
  void dispose() {
    _pageController.dispose();
    _name.dispose();
    _diagnosis.dispose();
    super.dispose();
  }

  void _next() {
    if (_step == 0 && _name.text.trim().length < 2) return;
    if (_step < 1) {
      setState(() => _step++);
      _pageController.nextPage(
        duration: const Duration(milliseconds: 250),
        curve: Curves.easeOut,
      );
    } else {
      _finish();
    }
  }

  Future<void> _finish() async {
    setState(() => _busy = true);
    try {
      await ref.read(patientRepositoryProvider).register(
            fullName: _name.text.trim(),
            birthDate: _birthDate,
            gender: _gender,
          );

      // Anything typed here lives in the private container until the patient
      // connects a doctor and consents to sharing it (spec 2.2).
      final String diagnosisText = _diagnosis.text.trim();
      if (diagnosisText.isNotEmpty) {
        final CareThread personal = await ref.read(threadRepositoryProvider).personal();
        await ref
            .read(threadRepositoryProvider)
            .createDiagnosis(personal.id, text: diagnosisText);
      }

      await ref.read(sessionProvider.notifier).refresh();
    } catch (error) {
      if (mounted) showApiError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.t('patient.self_register')),
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(3),
          child: LinearProgressIndicator(
            value: (_step + 1) / 2,
            minHeight: 3,
          ),
        ),
      ),
      body: SafeArea(
        child: Column(
          children: <Widget>[
            Expanded(
              child: PageView(
                controller: _pageController,
                physics: const NeverScrollableScrollPhysics(),
                children: <Widget>[
                  _StepOne(
                    nameController: _name,
                    birthDate: _birthDate,
                    gender: _gender,
                    onBirthDate: (DateTime value) => setState(() => _birthDate = value),
                    onGender: (String value) => setState(() => _gender = value),
                  ),
                  _StepTwo(diagnosisController: _diagnosis),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(AppSpacing.xl),
              child: FilledButton(
                onPressed: _busy ? null : _next,
                child: Text(
                  _step < 1 ? l10n.t('common.next') : l10n.t('common.done'),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _StepOne extends StatelessWidget {
  const _StepOne({
    required this.nameController,
    required this.birthDate,
    required this.gender,
    required this.onBirthDate,
    required this.onGender,
  });

  final TextEditingController nameController;
  final DateTime? birthDate;
  final String? gender;
  final ValueChanged<DateTime> onBirthDate;
  final ValueChanged<String> onGender;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;

    return SingleChildScrollView(
      padding: const EdgeInsets.all(AppSpacing.xl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          TextField(
            controller: nameController,
            textCapitalization: TextCapitalization.words,
            decoration: InputDecoration(
              labelText: l10n.t('patient.your_name'),
              prefixIcon: const Icon(Icons.person_outline_rounded),
            ),
          ),
          const SizedBox(height: AppSpacing.lg),
          InkWell(
            onTap: () async {
              final DateTime? picked = await showDatePicker(
                context: context,
                initialDate: birthDate ?? DateTime(1980),
                firstDate: DateTime(1920),
                lastDate: DateTime.now(),
              );
              if (picked != null) onBirthDate(picked);
            },
            child: InputDecorator(
              decoration: InputDecoration(
                labelText: l10n.t('patient.birth_date'),
                prefixIcon: const Icon(Icons.cake_outlined),
              ),
              child: Text(
                birthDate == null ? '—' : Formatters.date(birthDate!, l10n.languageCode),
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.lg),
          Row(
            children: <Widget>[
              Expanded(
                child: _GenderOption(
                  label: l10n.t('patient.gender_male'),
                  value: 'male',
                  selected: gender == 'male',
                  onTap: onGender,
                ),
              ),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: _GenderOption(
                  label: l10n.t('patient.gender_female'),
                  value: 'female',
                  selected: gender == 'female',
                  onTap: onGender,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _GenderOption extends StatelessWidget {
  const _GenderOption({
    required this.label,
    required this.value,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final String value;
  final bool selected;
  final ValueChanged<String> onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: () => onTap(value),
      borderRadius: BorderRadius.circular(AppSpacing.radiusMd),
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.lg),
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: selected ? AppColors.primaryLight : null,
          borderRadius: BorderRadius.circular(AppSpacing.radiusMd),
          border: Border.all(
            color: selected ? AppColors.primary : Theme.of(context).dividerColor,
            width: selected ? 1.5 : 1,
          ),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontWeight: FontWeight.w600,
            color: selected ? AppColors.primaryDark : null,
          ),
        ),
      ),
    );
  }
}

class _StepTwo extends StatelessWidget {
  const _StepTwo({required this.diagnosisController});

  final TextEditingController diagnosisController;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;

    return SingleChildScrollView(
      padding: const EdgeInsets.all(AppSpacing.xl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Text(
            l10n.t('patient.your_diagnosis'),
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            l10n.t('patient.your_diagnosis_hint'),
            style: const TextStyle(color: AppColors.textSecondary),
          ),
          const SizedBox(height: AppSpacing.lg),
          TextField(
            controller: diagnosisController,
            maxLines: 3,
            textCapitalization: TextCapitalization.sentences,
            decoration: InputDecoration(
              labelText: '${l10n.t('doctor.diagnosis')} (${l10n.t('common.optional')})',
            ),
          ),
        ],
      ),
    );
  }
}
