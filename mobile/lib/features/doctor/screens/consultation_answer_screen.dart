import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../core/theme/app_theme.dart';
import '../../../data/models/models.dart';
import '../../../shared/utils/formatters.dart';
import '../../../shared/widgets/common_widgets.dart';
import '../../../shared/widgets/loading_view.dart';

/// Claim and answer one consultation (spec 4.2 tab 2).
///
/// Before claiming, the doctor sees the question and the price but not the
/// patient's identity or clinical snapshot: they are choosing a question, not a
/// person. Claiming is exclusive — losing the race returns a clear 409.
class ConsultationAnswerScreen extends ConsumerStatefulWidget {
  const ConsultationAnswerScreen({super.key, required this.consultationId});

  final String consultationId;

  @override
  ConsumerState<ConsultationAnswerScreen> createState() =>
      _ConsultationAnswerScreenState();
}

class _ConsultationAnswerScreenState extends ConsumerState<ConsultationAnswerScreen> {
  final TextEditingController _answer = TextEditingController();
  Consultation? _consultation;
  bool _loading = true;
  bool _busy = false;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _answer.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final Consultation consultation =
          await ref.read(consultationRepositoryProvider).get(widget.consultationId);
      setState(() {
        _consultation = consultation;
        _error = null;
      });
    } catch (error) {
      setState(() => _error = error);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _claim() async {
    setState(() => _busy = true);
    try {
      final Consultation consultation =
          await ref.read(consultationRepositoryProvider).claim(widget.consultationId);
      setState(() => _consultation = consultation);
    } catch (error) {
      if (mounted) {
        showApiError(context, error);
        // Another doctor took it: leave, the list will refresh.
        Navigator.of(context).pop(true);
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _send() async {
    if (_answer.text.trim().length < 5) return;
    setState(() => _busy = true);
    try {
      await ref
          .read(consultationRepositoryProvider)
          .answer(widget.consultationId, _answer.text.trim());
      if (mounted) {
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

    if (_loading) {
      return const Scaffold(body: LoadingView());
    }
    if (_error != null || _consultation == null) {
      return Scaffold(
        appBar: AppBar(),
        body: ErrorView(error: _error ?? 'error', onRetry: _load),
      );
    }

    final Consultation consultation = _consultation!;
    final bool claimed = consultation.status == 'claimed';
    final bool answered = consultation.isAnswered;

    return Scaffold(
      appBar: AppBar(title: Text(consultation.patientName ?? '')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: <Widget>[
            AppCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Row(
                    children: <Widget>[
                      Expanded(
                        child: Text(
                          l10n.t('patient.your_question'),
                          style: const TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w700,
                            color: AppColors.textTertiary,
                          ),
                        ),
                      ),
                      MoneyText(
                        amountUzs: consultation.priceUzs,
                        style: const TextStyle(
                          fontWeight: FontWeight.w700,
                          color: AppColors.primary,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Text(
                    consultation.question,
                    style: Theme.of(context).textTheme.bodyLarge,
                  ),
                ],
              ),
            ),
            // The frozen clinical snapshot the patient consented to share.
            if (consultation.snapshot != null &&
                !consultation.snapshot!.isEmpty) ...<Widget>[
              const SizedBox(height: AppSpacing.lg),
              _SnapshotCard(snapshot: consultation.snapshot!),
            ],
            const SizedBox(height: AppSpacing.xl),
            if (answered) ...<Widget>[
              AppCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text(
                      l10n.t('patient.answer_received'),
                      style: const TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                        color: AppColors.ok,
                      ),
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    Text(consultation.answerText ?? ''),
                    if (consultation.rating != null) ...<Widget>[
                      const SizedBox(height: AppSpacing.md),
                      StarRating(rating: consultation.rating!.toDouble()),
                      if (consultation.review != null) ...<Widget>[
                        const SizedBox(height: 4),
                        Text(
                          consultation.review!,
                          style: const TextStyle(
                            fontStyle: FontStyle.italic,
                            color: AppColors.textSecondary,
                          ),
                        ),
                      ],
                    ],
                  ],
                ),
              ),
            ] else if (claimed) ...<Widget>[
              TextField(
                controller: _answer,
                maxLines: 8,
                autofocus: true,
                decoration: InputDecoration(
                  hintText: l10n.t('doctor.answer_hint'),
                  alignLabelWithHint: true,
                ),
              ),
              const SizedBox(height: AppSpacing.lg),
              FilledButton(
                onPressed: _busy ? null : _send,
                child: Text(l10n.t('doctor.send_answer')),
              ),
            ] else ...<Widget>[
              Container(
                padding: const EdgeInsets.all(AppSpacing.lg),
                decoration: BoxDecoration(
                  color: AppColors.warningSoft,
                  borderRadius: BorderRadius.circular(AppSpacing.radiusMd),
                ),
                child: Row(
                  children: <Widget>[
                    const Icon(Icons.schedule_rounded,
                        color: AppColors.warning, size: 20),
                    const SizedBox(width: AppSpacing.md),
                    Expanded(
                      child: Text(
                        '${l10n.t('doctor.deadline')}: '
                        '${Formatters.remaining(consultation.slaExpiresAt, l10n.languageCode)}',
                        style: const TextStyle(
                          color: AppColors.warning,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: AppSpacing.lg),
              FilledButton.icon(
                onPressed: _busy ? null : _claim,
                icon: const Icon(Icons.check_rounded),
                label: Text(l10n.t('doctor.accept')),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _SnapshotCard extends StatelessWidget {
  const _SnapshotCard({required this.snapshot});

  final ConsultationSnapshot snapshot;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              const Icon(Icons.folder_shared_outlined,
                  size: 18, color: AppColors.primary),
              const SizedBox(width: AppSpacing.sm),
              Text(
                l10n.t('patient.personal_data'),
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
              const Spacer(),
              if (snapshot.patientAge != null)
                Text(
                  '${snapshot.patientAge}',
                  style: const TextStyle(color: AppColors.textSecondary),
                ),
            ],
          ),
          if (snapshot.diagnoses.isNotEmpty) ...<Widget>[
            const SizedBox(height: AppSpacing.md),
            Text(
              l10n.t('doctor.diagnosis'),
              style: const TextStyle(
                fontSize: 11.5,
                fontWeight: FontWeight.w700,
                color: AppColors.textTertiary,
              ),
            ),
            const SizedBox(height: 4),
            for (final Map<String, dynamic> diagnosis in snapshot.diagnoses)
              Padding(
                padding: const EdgeInsets.only(bottom: 3),
                child: Row(
                  children: <Widget>[
                    Icon(
                      diagnosis['verified'] == true
                          ? Icons.verified_rounded
                          : Icons.schedule_rounded,
                      size: 13,
                      color: diagnosis['verified'] == true
                          ? AppColors.ok
                          : AppColors.warning,
                    ),
                    const SizedBox(width: 5),
                    Expanded(child: Text('${diagnosis['text']}')),
                  ],
                ),
              ),
          ],
          if (snapshot.medications.isNotEmpty) ...<Widget>[
            const SizedBox(height: AppSpacing.md),
            Text(
              l10n.t('doctor.medications'),
              style: const TextStyle(
                fontSize: 11.5,
                fontWeight: FontWeight.w700,
                color: AppColors.textTertiary,
              ),
            ),
            const SizedBox(height: 4),
            for (final Map<String, dynamic> medication in snapshot.medications)
              Text('• ${medication['name']} — ${medication['dose']}'),
          ],
          if (snapshot.recentReadings.isNotEmpty) ...<Widget>[
            const SizedBox(height: AppSpacing.md),
            Text(
              l10n.t('doctor.trends'),
              style: const TextStyle(
                fontSize: 11.5,
                fontWeight: FontWeight.w700,
                color: AppColors.textTertiary,
              ),
            ),
            const SizedBox(height: 4),
            for (final Map<String, dynamic> reading in snapshot.recentReadings)
              _ReadingSummary(reading: reading),
          ],
        ],
      ),
    );
  }
}

class _ReadingSummary extends StatelessWidget {
  const _ReadingSummary({required this.reading});

  final Map<String, dynamic> reading;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;
    final List<dynamic> points = (reading['points'] as List<dynamic>? ?? <dynamic>[]);
    if (points.isEmpty) return const SizedBox.shrink();

    final Map<String, dynamic> last =
        (points.last as Map<dynamic, dynamic>).cast<String, dynamic>();
    final Map<String, dynamic> label =
        (reading['label'] as Map<dynamic, dynamic>? ?? <dynamic, dynamic>{})
            .cast<String, dynamic>();

    return Padding(
      padding: const EdgeInsets.only(bottom: 3),
      child: Text(
        '• ${l10n.fromMap(label, fallback: '${reading['key']}')}: '
        '${last['value']}${last['value_secondary'] != null ? '/${last['value_secondary']}' : ''} '
        '${reading['unit']} (${points.length})',
      ),
    );
  }
}
