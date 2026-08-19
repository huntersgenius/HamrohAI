import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../core/theme/app_theme.dart';
import '../../../data/models/models.dart';
import '../../../shared/utils/formatters.dart';
import '../../../shared/widgets/common_widgets.dart';
import '../../../shared/widgets/loading_view.dart';

/// Tab 1 — "Bugun" (spec 5.2).
///
/// When the patient has several doctors, the switcher at the top picks which
/// care thread is active. Everything below it belongs to that thread only.
class PatientTodayTab extends ConsumerWidget {
  const PatientTodayTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppLocalizations l10n = context.l10n;
    final AsyncValue<List<CareThread>> threads = ref.watch(threadsProvider);

    return Scaffold(
      appBar: AppBar(title: Text(l10n.t('patient.tab_today'))),
      body: AsyncView<List<CareThread>>(
        value: threads,
        onRetry: () => ref.invalidate(threadsProvider),
        builder: (List<CareThread> all) {
          if (all.isEmpty) {
            return EmptyView(
              icon: Icons.today_outlined,
              title: l10n.t('patient.no_doctors'),
              message: l10n.t('patient.no_doctors_hint'),
            );
          }

          // Doctor threads first; the personal container is the fallback for a
          // patient who has not connected anyone yet.
          final List<CareThread> doctorThreads =
              all.where((CareThread t) => !t.isPersonal).toList();
          final List<CareThread> selectable = doctorThreads.isEmpty ? all : doctorThreads;

          final String? active = ref.watch(activeThreadIdProvider);
          final CareThread current = selectable.firstWhere(
            (CareThread t) => t.id == active,
            orElse: () => selectable.first,
          );

          return RefreshIndicator(
            onRefresh: () async {
              ref.invalidate(threadsProvider);
              ref.invalidate(todayProvider(current.id));
            },
            child: ListView(
              padding: const EdgeInsets.all(AppSpacing.lg),
              children: <Widget>[
                if (selectable.length > 1)
                  _ThreadSwitcher(
                    threads: selectable,
                    current: current,
                    onChanged: (CareThread thread) =>
                        ref.read(activeThreadIdProvider.notifier).state = thread.id,
                  ),
                _TodayContent(threadId: current.id),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _ThreadSwitcher extends StatelessWidget {
  const _ThreadSwitcher({
    required this.threads,
    required this.current,
    required this.onChanged,
  });

  final List<CareThread> threads;
  final CareThread current;
  final ValueChanged<CareThread> onChanged;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            l10n.t('patient.active_thread'),
            style: const TextStyle(
              fontSize: 11.5,
              fontWeight: FontWeight.w700,
              color: AppColors.textTertiary,
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          SizedBox(
            height: 40,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              itemCount: threads.length,
              separatorBuilder: (_, __) => const SizedBox(width: AppSpacing.sm),
              itemBuilder: (BuildContext context, int index) {
                final CareThread thread = threads[index];
                final bool selected = thread.id == current.id;
                return ChoiceChip(
                  selected: selected,
                  onSelected: (_) => onChanged(thread),
                  avatar: Icon(
                    thread.isPersonal
                        ? Icons.lock_outline_rounded
                        : Icons.medical_services_outlined,
                    size: 16,
                    color: selected ? AppColors.primaryDark : null,
                  ),
                  label: Text(
                    thread.isPersonal
                        ? l10n.t('patient.personal_data')
                        : thread.displayName,
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _TodayContent extends ConsumerStatefulWidget {
  const _TodayContent({required this.threadId});

  final String threadId;

  @override
  ConsumerState<_TodayContent> createState() => _TodayContentState();
}

class _TodayContentState extends ConsumerState<_TodayContent> {
  final Map<String, dynamic> _answers = <String, dynamic>{};
  bool _submitting = false;

  Future<void> _submit() async {
    if (_answers.isEmpty) return;
    setState(() => _submitting = true);
    try {
      await ref
          .read(threadRepositoryProvider)
          .submitCheckin(widget.threadId, answers: _answers);
      ref.invalidate(todayProvider(widget.threadId));
      if (mounted) {
        _answers.clear();
        showSuccess(context, context.l10n.t('patient.checkin_done'));
      }
    } catch (error) {
      if (mounted) showApiError(context, error);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  Future<void> _markTaken(MedicationDose dose) async {
    try {
      await ref.read(threadRepositoryProvider).markDoseTaken(widget.threadId, dose.id);
      ref.invalidate(todayProvider(widget.threadId));
    } catch (error) {
      if (mounted) showApiError(context, error);
    }
  }

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;
    final AsyncValue<TodayData> today = ref.watch(todayProvider(widget.threadId));

    return AsyncView<TodayData>(
      value: today,
      onRetry: () => ref.invalidate(todayProvider(widget.threadId)),
      builder: (TodayData data) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          // ------------------------------------------------- check-in card
          if (data.questions.isNotEmpty)
            AppCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: <Widget>[
                  Row(
                    children: <Widget>[
                      const Icon(
                        Icons.assignment_turned_in_outlined,
                        size: 20,
                        color: AppColors.primary,
                      ),
                      const SizedBox(width: AppSpacing.sm),
                      Expanded(
                        child: Text(
                          l10n.t('patient.checkin_title'),
                          style: const TextStyle(fontWeight: FontWeight.w700),
                        ),
                      ),
                      if (data.alreadySubmitted)
                        const Icon(
                          Icons.check_circle_rounded,
                          size: 20,
                          color: AppColors.ok,
                        ),
                    ],
                  ),
                  const SizedBox(height: AppSpacing.lg),
                  for (final CheckinQuestion question in data.questions)
                    _QuestionField(
                      question: question,
                      initialValue: data.submittedAnswers[question.key],
                      onChanged: (Object? value) {
                        if (value == null) {
                          _answers.remove(question.key);
                        } else {
                          _answers[question.key] = value;
                        }
                      },
                    ),
                  const SizedBox(height: AppSpacing.sm),
                  FilledButton(
                    onPressed: _submitting ? null : _submit,
                    child: Text(
                      data.alreadySubmitted
                          ? l10n.t('common.save')
                          : l10n.t('patient.mark'),
                    ),
                  ),
                ],
              ),
            ),

          // ------------------------------------------------- medications
          SectionHeader(title: l10n.t('patient.medications_today')),
          if (data.doses.isEmpty)
            AppCard(
              child: Center(
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
                  child: Text(
                    l10n.t('patient.no_doses'),
                    style: const TextStyle(color: AppColors.textTertiary),
                  ),
                ),
              ),
            )
          else
            for (final MedicationDose dose in data.doses)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                child: _DoseTile(dose: dose, onTaken: () => _markTaken(dose)),
              ),
        ],
      ),
    );
  }
}

class _QuestionField extends StatefulWidget {
  const _QuestionField({
    required this.question,
    required this.onChanged,
    this.initialValue,
  });

  final CheckinQuestion question;
  final ValueChanged<Object?> onChanged;
  final Object? initialValue;

  @override
  State<_QuestionField> createState() => _QuestionFieldState();
}

class _QuestionFieldState extends State<_QuestionField> {
  late final TextEditingController _primary;
  late final TextEditingController _secondary;
  String? _choice;

  @override
  void initState() {
    super.initState();
    final Object? initial = widget.initialValue;
    _primary = TextEditingController(
      text: initial is num ? '$initial' : (initial is String ? initial : ''),
    );
    _secondary = TextEditingController();
    if (initial is String) _choice = initial;
  }

  @override
  void dispose() {
    _primary.dispose();
    _secondary.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;
    final CheckinQuestion question = widget.question;
    final String prompt = l10n.fromMap(question.prompt, fallback: question.key);

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(prompt, style: const TextStyle(fontWeight: FontWeight.w500)),
          const SizedBox(height: AppSpacing.sm),
          switch (question.type) {
            'pair' => Row(
                children: <Widget>[
                  Expanded(
                    child: TextField(
                      controller: _primary,
                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      decoration: InputDecoration(
                        isDense: true,
                        hintText: l10n.t('chart.systolic'),
                      ),
                      onChanged: (_) => _emitPair(),
                    ),
                  ),
                  const Padding(
                    padding: EdgeInsets.symmetric(horizontal: AppSpacing.sm),
                    child: Text('/', style: TextStyle(fontSize: 18)),
                  ),
                  Expanded(
                    child: TextField(
                      controller: _secondary,
                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      decoration: InputDecoration(
                        isDense: true,
                        hintText: l10n.t('chart.diastolic'),
                      ),
                      onChanged: (_) => _emitPair(),
                    ),
                  ),
                ],
              ),
            'boolean' => Row(
                children: <Widget>[
                  Expanded(
                    child: _ChoiceButton(
                      label: l10n.t('common.yes'),
                      selected: _choice == 'true',
                      onTap: () {
                        setState(() => _choice = 'true');
                        widget.onChanged(true);
                      },
                    ),
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  Expanded(
                    child: _ChoiceButton(
                      label: l10n.t('common.no'),
                      selected: _choice == 'false',
                      onTap: () {
                        setState(() => _choice = 'false');
                        widget.onChanged(false);
                      },
                    ),
                  ),
                ],
              ),
            'choice' => Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.sm,
                children: question.options.map((Map<String, dynamic> option) {
                  final String value = '${option['value']}';
                  final Map<String, dynamic> label =
                      (option['label'] as Map<dynamic, dynamic>? ?? <dynamic, dynamic>{})
                          .cast<String, dynamic>();
                  return ChoiceChip(
                    selected: _choice == value,
                    label: Text(l10n.fromMap(label, fallback: value)),
                    onSelected: (_) {
                      setState(() => _choice = value);
                      widget.onChanged(value);
                    },
                  );
                }).toList(),
              ),
            _ => TextField(
                controller: _primary,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: InputDecoration(
                  isDense: true,
                  suffixText: question.unit,
                ),
                onChanged: (String value) => widget.onChanged(
                  double.tryParse(value.replaceAll(',', '.')),
                ),
              ),
          },
        ],
      ),
    );
  }

  void _emitPair() {
    final double? systolic = double.tryParse(_primary.text.replaceAll(',', '.'));
    final double? diastolic = double.tryParse(_secondary.text.replaceAll(',', '.'));
    if (systolic == null) {
      widget.onChanged(null);
      return;
    }
    widget.onChanged(<String, dynamic>{
      'value': systolic,
      'value_secondary': diastolic,
    });
  }
}

class _ChoiceButton extends StatelessWidget {
  const _ChoiceButton({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(AppSpacing.radiusMd),
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.md),
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: selected ? AppColors.primaryLight : null,
          borderRadius: BorderRadius.circular(AppSpacing.radiusMd),
          border: Border.all(
            color: selected ? AppColors.primary : Theme.of(context).dividerColor,
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

class _DoseTile extends StatelessWidget {
  const _DoseTile({required this.dose, required this.onTaken});

  final MedicationDose dose;
  final VoidCallback onTaken;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;
    final bool taken = dose.isTaken;

    return AppCard(
      padding: const EdgeInsets.all(AppSpacing.md),
      border: dose.isMissed ? AppColors.danger.withValues(alpha: 0.35) : null,
      child: Row(
        children: <Widget>[
          Container(
            width: 46,
            alignment: Alignment.center,
            child: Text(
              Formatters.time(dose.scheduledAt),
              style: TextStyle(
                fontWeight: FontWeight.w700,
                color: taken ? AppColors.textTertiary : AppColors.textPrimary,
              ),
            ),
          ),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(
                  dose.medicationName ?? '',
                  style: TextStyle(
                    fontWeight: FontWeight.w600,
                    decoration: taken ? TextDecoration.lineThrough : null,
                    color: taken ? AppColors.textTertiary : null,
                  ),
                ),
                if (dose.doseText != null)
                  Text(
                    dose.doseText!,
                    style: const TextStyle(
                      fontSize: 12.5,
                      color: AppColors.textSecondary,
                    ),
                  ),
                // Surfaced so the patient sees the call was registered.
                if (dose.confirmedByCall)
                  Row(
                    children: <Widget>[
                      const Icon(
                        Icons.phone_in_talk_rounded,
                        size: 12,
                        color: AppColors.textTertiary,
                      ),
                      const SizedBox(width: 4),
                      Text(
                        l10n.t('patient.call_reminders'),
                        style: const TextStyle(
                          fontSize: 11,
                          color: AppColors.textTertiary,
                        ),
                      ),
                    ],
                  ),
              ],
            ),
          ),
          if (taken)
            const Icon(Icons.check_circle_rounded, color: AppColors.ok)
          else
            FilledButton(
              onPressed: onTaken,
              style: FilledButton.styleFrom(
                minimumSize: const Size(0, 38),
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
              ),
              child: Text(l10n.t('patient.taken')),
            ),
        ],
      ),
    );
  }
}
