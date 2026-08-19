import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../core/theme/app_theme.dart';
import '../../../data/models/models.dart';
import '../../../shared/utils/formatters.dart';
import '../../../shared/widgets/common_widgets.dart';
import '../../../shared/widgets/loading_view.dart';
import 'consultation_answer_screen.dart';

/// Tab 2 — incoming consultation requests and answered history (spec 4.2).
class DoctorConsultationsTab extends ConsumerWidget {
  const DoctorConsultationsTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppLocalizations l10n = context.l10n;

    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: Text(l10n.t('doctor.tab_consultations')),
          bottom: TabBar(
            tabs: <Widget>[
              Tab(text: l10n.t('doctor.consultation_incoming')),
              Tab(text: l10n.t('doctor.consultation_history')),
            ],
          ),
        ),
        body: const TabBarView(
          children: <Widget>[
            _ConsultationList(isInbox: true),
            _ConsultationList(isInbox: false),
          ],
        ),
      ),
    );
  }
}

class _ConsultationList extends ConsumerWidget {
  const _ConsultationList({required this.isInbox});

  final bool isInbox;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppLocalizations l10n = context.l10n;
    final AsyncValue<Paged<ConsultationListItem>> value = isInbox
        ? ref.watch(consultationInboxProvider)
        : ref.watch(consultationHistoryProvider);

    return AsyncView<Paged<ConsultationListItem>>(
      value: value,
      onRetry: () => ref.invalidate(
        isInbox ? consultationInboxProvider : consultationHistoryProvider,
      ),
      builder: (Paged<ConsultationListItem> page) {
        if (page.items.isEmpty) {
          return EmptyView(
            icon: Icons.forum_outlined,
            title: l10n.t('doctor.no_consultations'),
          );
        }
        return RefreshIndicator(
          onRefresh: () async => ref.invalidate(
            isInbox ? consultationInboxProvider : consultationHistoryProvider,
          ),
          child: ListView.separated(
            padding: const EdgeInsets.all(AppSpacing.lg),
            itemCount: page.items.length,
            separatorBuilder: (_, __) => const SizedBox(height: AppSpacing.md),
            itemBuilder: (BuildContext context, int index) => _ConsultationCard(
              item: page.items[index],
              showRating: !isInbox,
            ),
          ),
        );
      },
    );
  }
}

class _ConsultationCard extends ConsumerWidget {
  const _ConsultationCard({required this.item, required this.showRating});

  final ConsultationListItem item;
  final bool showRating;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppLocalizations l10n = context.l10n;
    final ThemeData theme = Theme.of(context);

    return AppCard(
      onTap: () async {
        final bool? changed = await Navigator.of(context).push<bool>(
          MaterialPageRoute<bool>(
            builder: (_) => ConsultationAnswerScreen(consultationId: item.id),
          ),
        );
        if (changed ?? false) {
          ref.invalidate(consultationInboxProvider);
          ref.invalidate(consultationHistoryProvider);
          ref.invalidate(walletProvider);
        }
      },
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(
                child: Text(
                  item.displayName,
                  style: theme.textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              MoneyText(
                amountUzs: item.priceUzs,
                style: const TextStyle(
                  fontWeight: FontWeight.w700,
                  color: AppColors.primary,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            item.questionPreview,
            style: theme.textTheme.bodyMedium?.copyWith(
              color: AppColors.textSecondary,
            ),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
          const SizedBox(height: AppSpacing.md),
          Row(
            children: <Widget>[
              if (item.isClaimable) ...<Widget>[
                const Icon(
                  Icons.schedule_rounded,
                  size: 14,
                  color: AppColors.warning,
                ),
                const SizedBox(width: 4),
                Text(
                  '${l10n.t('doctor.deadline')}: '
                  '${Formatters.remaining(item.slaExpiresAt, l10n.languageCode)}',
                  style: const TextStyle(
                    fontSize: 12,
                    color: AppColors.warning,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ] else
                Text(
                  Formatters.relative(
                    item.answeredAt ?? item.createdAt,
                    l10n.languageCode,
                  ),
                  style: const TextStyle(
                    fontSize: 12,
                    color: AppColors.textTertiary,
                  ),
                ),
              const Spacer(),
              if (showRating && item.rating != null)
                StarRating(rating: item.rating!.toDouble(), size: 15),
            ],
          ),
        ],
      ),
    );
  }
}
