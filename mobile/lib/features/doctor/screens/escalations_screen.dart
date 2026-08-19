import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../core/theme/app_theme.dart';
import '../../../data/models/models.dart';
import '../../../shared/utils/formatters.dart';
import '../../../shared/widgets/common_widgets.dart';
import '../../../shared/widgets/loading_view.dart';

/// Questions the AI forwarded to this doctor (spec 8).
///
/// These are not paid consultations: they are the continuation of an existing
/// relationship, so answering costs nothing and lands back in the same thread.
class EscalationsScreen extends ConsumerWidget {
  const EscalationsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppLocalizations l10n = context.l10n;
    final AsyncValue<Paged<Escalation>> escalations = ref.watch(escalationsProvider);

    return Scaffold(
      appBar: AppBar(title: Text(l10n.t('doctor.escalations'))),
      body: AsyncView<Paged<Escalation>>(
        value: escalations,
        onRetry: () => ref.invalidate(escalationsProvider),
        builder: (Paged<Escalation> page) {
          if (page.items.isEmpty) {
            return EmptyView(
              icon: Icons.mark_chat_read_outlined,
              title: l10n.t('common.empty'),
            );
          }
          return RefreshIndicator(
            onRefresh: () async => ref.invalidate(escalationsProvider),
            child: ListView.separated(
              padding: const EdgeInsets.all(AppSpacing.lg),
              itemCount: page.items.length,
              separatorBuilder: (_, __) => const SizedBox(height: AppSpacing.md),
              itemBuilder: (BuildContext context, int index) =>
                  _EscalationCard(escalation: page.items[index]),
            ),
          );
        },
      ),
    );
  }
}

class _EscalationCard extends ConsumerStatefulWidget {
  const _EscalationCard({required this.escalation});

  final Escalation escalation;

  @override
  ConsumerState<_EscalationCard> createState() => _EscalationCardState();
}

class _EscalationCardState extends ConsumerState<_EscalationCard> {
  final TextEditingController _answer = TextEditingController();
  bool _expanded = false;
  bool _busy = false;

  @override
  void dispose() {
    _answer.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    if (_answer.text.trim().length < 2) return;
    setState(() => _busy = true);
    try {
      await ref
          .read(aiRepositoryProvider)
          .answerEscalation(widget.escalation.id, _answer.text.trim());
      ref.invalidate(escalationsProvider);
      if (mounted) {
        showSuccess(context, context.l10n.t('common.done'));
        setState(() => _expanded = false);
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
    final Escalation escalation = widget.escalation;

    return AppCard(
      onTap: () => setState(() => _expanded = !_expanded),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              CircleAvatar(
                radius: 16,
                backgroundColor: AppColors.primaryLight,
                child: Text(
                  Formatters.initials(escalation.patientName),
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: AppColors.primaryDark,
                  ),
                ),
              ),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: Text(
                  escalation.patientName ?? '',
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
              ),
              Text(
                Formatters.relative(escalation.createdAt, l10n.languageCode),
                style: const TextStyle(
                  fontSize: 11.5,
                  color: AppColors.textTertiary,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.md),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(AppSpacing.md),
            decoration: BoxDecoration(
              color: AppColors.surfaceAlt,
              borderRadius: BorderRadius.circular(AppSpacing.radiusMd),
            ),
            child: Text(escalation.question),
          ),
          if (!escalation.isOpen && escalation.answerText != null) ...<Widget>[
            const SizedBox(height: AppSpacing.md),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(AppSpacing.md),
              decoration: BoxDecoration(
                color: AppColors.okSoft,
                borderRadius: BorderRadius.circular(AppSpacing.radiusMd),
              ),
              child: Text(escalation.answerText!),
            ),
          ],
          if (escalation.isOpen) ...<Widget>[
            const SizedBox(height: AppSpacing.md),
            if (!_expanded)
              FilledButton.tonal(
                onPressed: () => setState(() => _expanded = true),
                child: Text(l10n.t('doctor.answer')),
              )
            else ...<Widget>[
              TextField(
                controller: _answer,
                autofocus: true,
                maxLines: 4,
                decoration: InputDecoration(
                  hintText: l10n.t('doctor.answer_hint'),
                ),
              ),
              const SizedBox(height: AppSpacing.md),
              FilledButton(
                onPressed: _busy ? null : _send,
                child: Text(l10n.t('common.send')),
              ),
            ],
          ],
        ],
      ),
    );
  }
}
