import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../core/theme/app_theme.dart';
import '../../../data/models/models.dart';
import '../../../shared/utils/formatters.dart';
import '../../../shared/widgets/common_widgets.dart';
import '../../../shared/widgets/loading_view.dart';

/// "Yangi maslahat so'rash" (spec 5.2 tab 3B).
///
/// Steps: choose a doctor (by name, or matched by specialty) → decide which
/// care thread the question relates to → write it → pay → wait.
class NewConsultationFlow extends ConsumerStatefulWidget {
  const NewConsultationFlow({super.key});

  @override
  ConsumerState<NewConsultationFlow> createState() => _NewConsultationFlowState();
}

class _NewConsultationFlowState extends ConsumerState<NewConsultationFlow> {
  int _step = 0;

  DoctorSearchItem? _doctor;
  String? _specialty;
  CareThread? _thread;
  bool _shareData = true;
  final TextEditingController _question = TextEditingController();
  PriceQuote? _quote;
  bool _busy = false;

  @override
  void dispose() {
    _question.dispose();
    super.dispose();
  }

  Future<void> _loadQuote() async {
    try {
      final PriceQuote quote = await ref.read(consultationRepositoryProvider).quote(
            specialty: _specialty,
            doctorUserId: _doctor?.userId,
          );
      if (mounted) setState(() => _quote = quote);
    } catch (error) {
      if (mounted) showApiError(context, error);
    }
  }

  Future<void> _submit() async {
    if (_question.text.trim().length < 5) return;
    final String? provider = await _pickPaymentProvider(context);
    if (provider == null) return;

    setState(() => _busy = true);
    try {
      final Map<String, dynamic> response =
          await ref.read(consultationRepositoryProvider).create(
                doctorUserId: _doctor?.userId,
                specialty: _doctor == null ? _specialty : null,
                question: _question.text.trim(),
                careThreadId: _thread?.id,
                shareClinicalData: _thread != null && _shareData,
                paymentProvider: provider,
              );

      final String? checkoutUrl = response['checkout_url'] as String?;
      if (checkoutUrl != null) {
        final Uri uri = Uri.parse(checkoutUrl);
        if (await canLaunchUrl(uri)) {
          await launchUrl(uri, mode: LaunchMode.externalApplication);
        }
      }
      // The request only becomes visible to doctors once the payment webhook
      // confirms it (spec 7), so the list is refreshed on return.
      if (mounted) Navigator.of(context).pop(true);
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
        title: Text(l10n.t('patient.new_consultation')),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_rounded),
          onPressed: () {
            if (_step == 0) {
              Navigator.of(context).pop();
            } else {
              setState(() => _step--);
            }
          },
        ),
      ),
      body: SafeArea(
        child: switch (_step) {
          0 => _ChooseTargetStep(
              onDoctor: (DoctorSearchItem doctor) {
                setState(() {
                  _doctor = doctor;
                  _specialty = doctor.specialty;
                  _step = 1;
                });
                _loadQuote();
              },
              onSpecialty: (String specialty) {
                setState(() {
                  _specialty = specialty;
                  _doctor = null;
                  _step = 1;
                });
                _loadQuote();
              },
            ),
          1 => _ChooseThreadStep(
              onSelected: (CareThread? thread, bool share) {
                setState(() {
                  _thread = thread;
                  _shareData = share;
                  _step = 2;
                });
              },
            ),
          _ => _QuestionStep(
              controller: _question,
              quote: _quote,
              doctor: _doctor,
              busy: _busy,
              onSubmit: _submit,
            ),
        },
      ),
    );
  }
}

class _ChooseTargetStep extends ConsumerStatefulWidget {
  const _ChooseTargetStep({required this.onDoctor, required this.onSpecialty});

  final ValueChanged<DoctorSearchItem> onDoctor;
  final ValueChanged<String> onSpecialty;

  @override
  ConsumerState<_ChooseTargetStep> createState() => _ChooseTargetStepState();
}

class _ChooseTargetStepState extends ConsumerState<_ChooseTargetStep> {
  final TextEditingController _search = TextEditingController();
  List<DoctorSearchItem> _results = <DoctorSearchItem>[];
  bool _searching = false;
  bool _byName = true;

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Future<void> _runSearch() async {
    setState(() => _searching = true);
    try {
      final List<DoctorSearchItem> results =
          await ref.read(doctorRepositoryProvider).search(query: _search.text.trim());
      if (mounted) setState(() => _results = results);
    } catch (error) {
      if (mounted) showApiError(context, error);
    } finally {
      if (mounted) setState(() => _searching = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;
    final AsyncValue<List<SpecialtyOption>> specialties = ref.watch(specialtiesProvider);

    return ListView(
      padding: const EdgeInsets.all(AppSpacing.lg),
      children: <Widget>[
        Row(
          children: <Widget>[
            Expanded(
              child: _ModeButton(
                label: l10n.t('patient.choose_known_doctor'),
                selected: _byName,
                onTap: () => setState(() => _byName = true),
              ),
            ),
            const SizedBox(width: AppSpacing.sm),
            Expanded(
              child: _ModeButton(
                label: l10n.t('patient.find_doctor'),
                selected: !_byName,
                onTap: () => setState(() => _byName = false),
              ),
            ),
          ],
        ),
        const SizedBox(height: AppSpacing.xl),
        if (_byName) ...<Widget>[
          TextField(
            controller: _search,
            decoration: InputDecoration(
              labelText: l10n.t('patient.search_by_name'),
              prefixIcon: const Icon(Icons.search_rounded),
              suffixIcon: IconButton(
                icon: const Icon(Icons.arrow_forward_rounded),
                onPressed: _runSearch,
              ),
            ),
            onSubmitted: (_) => _runSearch(),
          ),
          const SizedBox(height: AppSpacing.lg),
          if (_searching)
            const LinearProgressIndicator(minHeight: 2)
          else
            for (final DoctorSearchItem doctor in _results)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.md),
                child: _DoctorResultCard(
                  doctor: doctor,
                  onSelect: () => widget.onDoctor(doctor),
                ),
              ),
        ] else
          specialties.when(
            data: (List<SpecialtyOption> options) => Column(
              children: options
                  .map(
                    (SpecialtyOption option) => Padding(
                      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                      child: AppCard(
                        padding: const EdgeInsets.all(AppSpacing.md),
                        onTap: () => widget.onSpecialty(option.code),
                        child: Row(
                          children: <Widget>[
                            Expanded(
                              child: Text(
                                l10n.fromMap(option.name),
                                style: const TextStyle(
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ),
                            MoneyText(
                              amountUzs: option.recommendedPriceUzs,
                              style: const TextStyle(
                                color: AppColors.textSecondary,
                                fontSize: 13,
                              ),
                            ),
                            const SizedBox(width: AppSpacing.sm),
                            const Icon(
                              Icons.chevron_right_rounded,
                              color: AppColors.textTertiary,
                            ),
                          ],
                        ),
                      ),
                    ),
                  )
                  .toList(),
            ),
            loading: () => const LinearProgressIndicator(minHeight: 2),
            error: (Object error, StackTrace _) => ErrorView(error: error),
          ),
      ],
    );
  }
}

class _ModeButton extends StatelessWidget {
  const _ModeButton({
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
        padding: const EdgeInsets.symmetric(
          vertical: AppSpacing.lg,
          horizontal: AppSpacing.md,
        ),
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
          textAlign: TextAlign.center,
          style: TextStyle(
            fontWeight: FontWeight.w600,
            fontSize: 13,
            color: selected ? AppColors.primaryDark : null,
          ),
        ),
      ),
    );
  }
}

class _DoctorResultCard extends StatelessWidget {
  const _DoctorResultCard({required this.doctor, required this.onSelect});

  final DoctorSearchItem doctor;
  final VoidCallback onSelect;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;

    return AppCard(
      onTap: onSelect,
      child: Row(
        children: <Widget>[
          CircleAvatar(
            radius: 22,
            backgroundColor: AppColors.primaryLight,
            child: Text(
              Formatters.initials(doctor.fullName),
              style: const TextStyle(
                color: AppColors.primaryDark,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(
                  doctor.fullName,
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
                Text(
                  doctor.specialty,
                  style: const TextStyle(
                    fontSize: 12.5,
                    color: AppColors.textSecondary,
                  ),
                ),
                const SizedBox(height: 3),
                StarRating(
                  rating: doctor.ratingAverage,
                  count: doctor.ratingCount,
                  size: 13,
                ),
              ],
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: <Widget>[
              MoneyText(
                amountUzs: doctor.consultationPriceUzs,
                style: const TextStyle(
                  fontWeight: FontWeight.w700,
                  color: AppColors.primary,
                  fontSize: 13,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                l10n.t('patient.choose'),
                style: const TextStyle(
                  fontSize: 12,
                  color: AppColors.primary,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// Which care thread the question relates to — this decides exactly what
/// clinical data the answering doctor will see (spec 5.2 tab 3B).
class _ChooseThreadStep extends ConsumerWidget {
  const _ChooseThreadStep({required this.onSelected});

  final void Function(CareThread?, bool) onSelected;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppLocalizations l10n = context.l10n;
    final AsyncValue<List<CareThread>> threads = ref.watch(threadsProvider);

    return AsyncView<List<CareThread>>(
      value: threads,
      builder: (List<CareThread> all) => ListView(
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: <Widget>[
          Text(
            l10n.t('patient.related_thread'),
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
          ),
          const SizedBox(height: AppSpacing.lg),
          for (final CareThread thread in all)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.sm),
              child: AppCard(
                onTap: () => onSelected(thread, true),
                child: Row(
                  children: <Widget>[
                    Icon(
                      thread.isPersonal
                          ? Icons.lock_outline_rounded
                          : Icons.medical_services_outlined,
                      color: AppColors.primary,
                    ),
                    const SizedBox(width: AppSpacing.md),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: <Widget>[
                          Text(
                            thread.isPersonal
                                ? l10n.t('patient.personal_data')
                                : thread.displayName,
                            style: const TextStyle(fontWeight: FontWeight.w600),
                          ),
                          if (thread.primaryDiagnosis != null)
                            Text(
                              thread.primaryDiagnosis!,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                fontSize: 12.5,
                                color: AppColors.textSecondary,
                              ),
                            ),
                        ],
                      ),
                    ),
                    const Icon(Icons.chevron_right_rounded,
                        color: AppColors.textTertiary),
                  ],
                ),
              ),
            ),
          const SizedBox(height: AppSpacing.sm),
          // Nothing clinical is attached in this case.
          OutlinedButton.icon(
            onPressed: () => onSelected(null, false),
            icon: const Icon(Icons.add_circle_outline_rounded, size: 18),
            label: Text(l10n.t('patient.unrelated')),
          ),
        ],
      ),
    );
  }
}

class _QuestionStep extends StatelessWidget {
  const _QuestionStep({
    required this.controller,
    required this.quote,
    required this.doctor,
    required this.busy,
    required this.onSubmit,
  });

  final TextEditingController controller;
  final PriceQuote? quote;
  final DoctorSearchItem? doctor;
  final bool busy;
  final VoidCallback onSubmit;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;

    return ListView(
      padding: const EdgeInsets.all(AppSpacing.lg),
      children: <Widget>[
        if (doctor != null)
          AppCard(
            padding: const EdgeInsets.all(AppSpacing.md),
            child: Row(
              children: <Widget>[
                CircleAvatar(
                  radius: 18,
                  backgroundColor: AppColors.primaryLight,
                  child: Text(
                    Formatters.initials(doctor!.fullName),
                    style: const TextStyle(
                      fontSize: 13,
                      color: AppColors.primaryDark,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: Text(
                    doctor!.fullName,
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                ),
              ],
            ),
          ),
        const SizedBox(height: AppSpacing.lg),
        TextField(
          controller: controller,
          maxLines: 7,
          autofocus: true,
          textCapitalization: TextCapitalization.sentences,
          decoration: InputDecoration(
            labelText: l10n.t('patient.your_question'),
            hintText: l10n.t('patient.question_hint'),
            alignLabelWithHint: true,
          ),
        ),
        const SizedBox(height: AppSpacing.xl),
        if (quote != null)
          AppCard(
            child: Column(
              children: <Widget>[
                Row(
                  children: <Widget>[
                    Expanded(child: Text(l10n.t('patient.price'))),
                    MoneyText(
                      amountUzs: quote!.priceUzs,
                      style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w700,
                        color: AppColors.primary,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: AppSpacing.sm),
                Row(
                  children: <Widget>[
                    const Icon(Icons.schedule_rounded,
                        size: 14, color: AppColors.textTertiary),
                    const SizedBox(width: 5),
                    Expanded(
                      child: Text(
                        l10n.tp('patient.waiting_hint', <String, Object?>{
                          'hours': quote!.slaHours,
                        }),
                        style: const TextStyle(
                          fontSize: 12,
                          color: AppColors.textTertiary,
                        ),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        const SizedBox(height: AppSpacing.xl),
        FilledButton.icon(
          onPressed: busy ? null : onSubmit,
          icon: const Icon(Icons.payment_rounded),
          label: Text(l10n.t('patient.pay_and_send')),
        ),
      ],
    );
  }
}

/// Card in the patient's consultation list, including the rating prompt and
/// the refund notice when nobody answered in time.
class ConsultationCard extends ConsumerStatefulWidget {
  const ConsultationCard({super.key, required this.consultation});

  final Consultation consultation;

  @override
  ConsumerState<ConsultationCard> createState() => _ConsultationCardState();
}

class _ConsultationCardState extends ConsumerState<ConsultationCard> {
  int _rating = 0;
  final TextEditingController _review = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _review.dispose();
    super.dispose();
  }

  Future<void> _rate() async {
    if (_rating == 0) return;
    setState(() => _busy = true);
    try {
      await ref.read(consultationRepositoryProvider).rate(
            widget.consultation.id,
            _rating,
            _review.text.trim(),
          );
      ref.invalidate(myConsultationsProvider);
      if (mounted) showSuccess(context, context.l10n.t('common.done'));
    } catch (error) {
      if (mounted) showApiError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;
    final Consultation consultation = widget.consultation;

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(
                child: Text(
                  consultation.doctorName ?? consultation.specialty,
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
              ),
              _StatusChip(status: consultation.status),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            consultation.question,
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(color: AppColors.textSecondary),
          ),

          // ------------------------------------------------- waiting
          if (consultation.isWaiting) ...<Widget>[
            const SizedBox(height: AppSpacing.md),
            Row(
              children: <Widget>[
                const SizedBox(
                  width: 14,
                  height: 14,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Text(
                    '${l10n.t('patient.waiting_answer')} '
                    '(${Formatters.remaining(consultation.slaExpiresAt, l10n.languageCode)})',
                    style: const TextStyle(
                      fontSize: 12.5,
                      color: AppColors.textSecondary,
                    ),
                  ),
                ),
              ],
            ),
          ],

          // -------------------------------------------------- answer
          if (consultation.isAnswered) ...<Widget>[
            const SizedBox(height: AppSpacing.md),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(AppSpacing.md),
              decoration: BoxDecoration(
                color: AppColors.okSoft,
                borderRadius: BorderRadius.circular(AppSpacing.radiusMd),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text(
                    l10n.t('patient.answer_received'),
                    style: const TextStyle(
                      fontSize: 11.5,
                      fontWeight: FontWeight.w700,
                      color: AppColors.ok,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(consultation.answerText ?? ''),
                ],
              ),
            ),
          ],

          // -------------------------------------------------- rating
          if (consultation.isAnswered && !consultation.isRated) ...<Widget>[
            const SizedBox(height: AppSpacing.md),
            const Divider(height: 1),
            const SizedBox(height: AppSpacing.sm),
            Text(
              l10n.t('patient.rate_hint'),
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: AppSpacing.sm),
            StarRating(
              rating: _rating.toDouble(),
              onChanged: (int value) => setState(() => _rating = value),
            ),
            if (_rating > 0) ...<Widget>[
              const SizedBox(height: AppSpacing.md),
              TextField(
                controller: _review,
                maxLines: 2,
                decoration: InputDecoration(
                  hintText: l10n.t('patient.review_hint'),
                  isDense: true,
                ),
              ),
              const SizedBox(height: AppSpacing.md),
              FilledButton(
                onPressed: _busy ? null : _rate,
                child: Text(l10n.t('common.send')),
              ),
            ],
          ] else if (consultation.isRated) ...<Widget>[
            const SizedBox(height: AppSpacing.md),
            StarRating(rating: consultation.rating?.toDouble(), size: 15),
          ],

          // ------------------------------------------------- refunded
          if (consultation.isRefunded) ...<Widget>[
            const SizedBox(height: AppSpacing.md),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(AppSpacing.md),
              decoration: BoxDecoration(
                color: AppColors.warningSoft,
                borderRadius: BorderRadius.circular(AppSpacing.radiusMd),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text(
                    l10n.t('patient.refunded_title'),
                    style: const TextStyle(
                      fontWeight: FontWeight.w700,
                      color: AppColors.warning,
                    ),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    l10n.t('patient.refunded_body'),
                    style: const TextStyle(fontSize: 13),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _StatusChip extends StatelessWidget {
  const _StatusChip({required this.status});

  final String status;

  @override
  Widget build(BuildContext context) {
    final (Color color, IconData icon) = switch (status) {
      'answered' || 'rated' => (AppColors.ok, Icons.check_circle_rounded),
      'refunded' => (AppColors.warning, Icons.replay_rounded),
      'claimed' => (AppColors.info, Icons.edit_note_rounded),
      _ => (AppColors.textTertiary, Icons.schedule_rounded),
    };
    return Icon(icon, size: 18, color: color);
  }
}

Future<String?> _pickPaymentProvider(BuildContext context) {
  final AppLocalizations l10n = context.l10n;
  return showModalBottomSheet<String>(
    context: context,
    builder: (BuildContext context) => SafeArea(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Padding(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Text(
              l10n.t('patient.choose_payment'),
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
            ),
          ),
          ListTile(
            leading: const Icon(Icons.payment_rounded),
            title: const Text('Click'),
            onTap: () => Navigator.of(context).pop('click'),
          ),
          ListTile(
            leading: const Icon(Icons.credit_card_rounded),
            title: const Text('Payme'),
            onTap: () => Navigator.of(context).pop('payme'),
          ),
          const SizedBox(height: AppSpacing.lg),
        ],
      ),
    ),
  );
}
