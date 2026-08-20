import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../core/theme/app_theme.dart';
import '../../../data/models/models.dart';
import '../../../shared/utils/formatters.dart';
import '../../../shared/widgets/loading_view.dart';
import 'consultation_flow.dart';

/// Tab 3 — "Yordam": the AI companion and paid consultations, side by side
/// but as two entirely separate flows (spec 5.2 tab 3, spec 8).
class PatientHelpTab extends ConsumerStatefulWidget {
  const PatientHelpTab({super.key});

  @override
  ConsumerState<PatientHelpTab> createState() => _PatientHelpTabState();
}

class _PatientHelpTabState extends ConsumerState<PatientHelpTab>
    with SingleTickerProviderStateMixin {
  late final TabController _tabController = TabController(length: 2, vsync: this);

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.t('patient.tab_help')),
        bottom: TabBar(
          controller: _tabController,
          tabs: <Widget>[
            Tab(text: l10n.t('patient.ai_tab')),
            Tab(text: l10n.t('patient.consult_tab')),
          ],
        ),
      ),
      body: TabBarView(
        controller: _tabController,
        children: <Widget>[
          AiChatView(
            onGoToConsultation: () => _tabController.animateTo(1),
          ),
          const ConsultationListView(),
        ],
      ),
    );
  }
}

/// Sub-tab A — the AI companion.
class AiChatView extends ConsumerStatefulWidget {
  const AiChatView({super.key, required this.onGoToConsultation});

  final VoidCallback onGoToConsultation;

  @override
  ConsumerState<AiChatView> createState() => _AiChatViewState();
}

class _AiChatViewState extends ConsumerState<AiChatView> {
  final TextEditingController _input = TextEditingController();
  final ScrollController _scroll = ScrollController();

  List<AiMessage> _messages = <AiMessage>[];
  String? _threadId;
  bool _sending = false;
  bool _loading = true;
  bool _suggestConsultation = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final List<CareThread> threads = await ref.read(threadRepositoryProvider).list();

      // Chat inside the active doctor thread, or the personal container when
      // there is no doctor yet — the assistant's context follows the thread.
      final String? active = ref.read(activeThreadIdProvider);
      final CareThread thread = threads.firstWhere(
        (CareThread t) => t.id == active,
        orElse: () => threads.firstWhere(
          (CareThread t) => !t.isPersonal,
          orElse: () =>
              threads.isNotEmpty ? threads.first : throw StateError('no thread'),
        ),
      );

      final List<AiMessage> messages =
          await ref.read(aiRepositoryProvider).messages(thread.id);
      if (!mounted) return;
      setState(() {
        _threadId = thread.id;
        _messages = messages;
      });
      _scrollToEnd();
    } catch (_) {
      // With no thread at all the composer still works: the server creates the
      // personal container on the first message.
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _scrollToEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(
          _scroll.position.maxScrollExtent,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      }
    });
  }

  Future<void> _send() async {
    final String text = _input.text.trim();
    if (text.isEmpty || _sending) return;

    setState(() {
      _sending = true;
      _input.clear();
      _messages = <AiMessage>[
        ..._messages,
        AiMessage(
          id: 'local-${DateTime.now().microsecondsSinceEpoch}',
          careThreadId: _threadId ?? '',
          role: 'patient',
          content: text,
          createdAt: DateTime.now(),
        ),
      ];
    });
    _scrollToEnd();

    try {
      final AiReply reply = await ref
          .read(aiRepositoryProvider)
          .ask(message: text, careThreadId: _threadId);
      if (!mounted) return;
      setState(() {
        _threadId = reply.message.careThreadId;
        _messages = <AiMessage>[..._messages, reply.message];
        _suggestConsultation = reply.suggestPaidConsultation;
      });
      _scrollToEnd();
    } catch (error) {
      if (mounted) showApiError(context, error);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;

    return Column(
      children: <Widget>[
        Expanded(
          child: _loading
              ? const LoadingView()
              : ListView(
                  controller: _scroll,
                  padding: const EdgeInsets.all(AppSpacing.lg),
                  children: <Widget>[
                    const _GreetingCard(),
                    for (final AiMessage message in _messages)
                      _MessageBubble(message: message),
                    if (_sending)
                      const Padding(
                        padding: EdgeInsets.only(top: AppSpacing.md),
                        child: Align(
                          alignment: Alignment.centerLeft,
                          child: SizedBox(
                            width: 22,
                            height: 22,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          ),
                        ),
                      ),
                    // Shown only when the patient has no assigned doctor.
                    if (_suggestConsultation)
                      Padding(
                        padding: const EdgeInsets.only(top: AppSpacing.lg),
                        child: FilledButton.icon(
                          onPressed: widget.onGoToConsultation,
                          icon: const Icon(Icons.medical_services_outlined),
                          label: Text(l10n.t('patient.ai_no_doctor_cta')),
                        ),
                      ),
                  ],
                ),
        ),
        SafeArea(
          top: false,
          child: Container(
            padding: const EdgeInsets.all(AppSpacing.md),
            decoration: BoxDecoration(
              color: Theme.of(context).cardTheme.color,
              border: Border(
                top: BorderSide(color: Theme.of(context).dividerColor),
              ),
            ),
            child: Row(
              children: <Widget>[
                Expanded(
                  child: TextField(
                    controller: _input,
                    minLines: 1,
                    maxLines: 4,
                    textCapitalization: TextCapitalization.sentences,
                    decoration: InputDecoration(
                      hintText: l10n.t('patient.ai_hint'),
                      isDense: true,
                      contentPadding: const EdgeInsets.symmetric(
                        horizontal: AppSpacing.lg,
                        vertical: AppSpacing.md,
                      ),
                    ),
                    onSubmitted: (_) => _send(),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                IconButton.filled(
                  onPressed: _sending ? null : _send,
                  icon: const Icon(Icons.send_rounded),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _GreetingCard extends StatelessWidget {
  const _GreetingCard();

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;

    return Container(
      margin: const EdgeInsets.only(bottom: AppSpacing.lg),
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: AppColors.primaryLight,
        borderRadius: BorderRadius.circular(AppSpacing.radiusLg),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              const Icon(Icons.auto_awesome_rounded,
                  size: 18, color: AppColors.primaryDark),
              const SizedBox(width: AppSpacing.sm),
              Text(
                l10n.t('patient.ai_tab'),
                style: const TextStyle(
                  fontWeight: FontWeight.w700,
                  color: AppColors.primaryDark,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            l10n.t('patient.ai_greeting'),
            style: const TextStyle(fontSize: 13.5, height: 1.4),
          ),
          const SizedBox(height: AppSpacing.sm),
          // The safety boundary, stated up front rather than only on refusal.
          Text(
            l10n.t('patient.ai_disclaimer'),
            style: const TextStyle(
              fontSize: 12,
              color: AppColors.textSecondary,
              fontStyle: FontStyle.italic,
              height: 1.35,
            ),
          ),
        ],
      ),
    );
  }
}

class _MessageBubble extends StatelessWidget {
  const _MessageBubble({required this.message});

  final AiMessage message;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;
    final bool mine = message.isFromPatient;
    final bool emergency = message.isEmergency;

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Align(
        alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
        child: ConstrainedBox(
          constraints: BoxConstraints(
            maxWidth: MediaQuery.of(context).size.width * 0.82,
          ),
          child: Column(
            crossAxisAlignment: mine ? CrossAxisAlignment.end : CrossAxisAlignment.start,
            children: <Widget>[
              if (message.isFromDoctor)
                Padding(
                  padding: const EdgeInsets.only(bottom: 4, left: 4),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      const Icon(Icons.medical_services_rounded,
                          size: 12, color: AppColors.primary),
                      const SizedBox(width: 4),
                      Text(
                        l10n.t('patient.tab_doctors'),
                        style: const TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                          color: AppColors.primary,
                        ),
                      ),
                    ],
                  ),
                ),
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: AppSpacing.lg,
                  vertical: AppSpacing.md,
                ),
                decoration: BoxDecoration(
                  color: emergency
                      ? AppColors.dangerSoft
                      : mine
                          ? AppColors.primary
                          : Theme.of(context).cardTheme.color,
                  borderRadius: BorderRadius.only(
                    topLeft: const Radius.circular(AppSpacing.radiusLg),
                    topRight: const Radius.circular(AppSpacing.radiusLg),
                    bottomLeft: Radius.circular(mine ? AppSpacing.radiusLg : 4),
                    bottomRight: Radius.circular(mine ? 4 : AppSpacing.radiusLg),
                  ),
                  border: mine
                      ? null
                      : Border.all(
                          color: emergency
                              ? AppColors.danger.withValues(alpha: 0.4)
                              : Theme.of(context).dividerColor,
                        ),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    if (emergency)
                      const Padding(
                        padding: EdgeInsets.only(bottom: 6),
                        child: Row(
                          children: <Widget>[
                            Icon(Icons.emergency_rounded,
                                size: 16, color: AppColors.danger),
                            SizedBox(width: 6),
                            Text(
                              '103',
                              style: TextStyle(
                                fontWeight: FontWeight.w700,
                                color: AppColors.danger,
                              ),
                            ),
                          ],
                        ),
                      ),
                    Text(
                      message.content,
                      style: TextStyle(
                        color: mine ? Colors.white : null,
                        height: 1.4,
                      ),
                    ),
                  ],
                ),
              ),
              // Which approved protocol backed the answer.
              if (message.citations.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 5, left: 4),
                  child: Wrap(
                    spacing: 6,
                    children: message.citations
                        .take(2)
                        .map(
                          (Map<String, dynamic> citation) => Text(
                            '${l10n.t('patient.ai_sources')}: '
                            '${citation['protocol_title'] ?? ''}',
                            style: const TextStyle(
                              fontSize: 10.5,
                              color: AppColors.textTertiary,
                            ),
                          ),
                        )
                        .toList(),
                  ),
                ),
              if (message.createdAt != null)
                Padding(
                  padding: const EdgeInsets.only(top: 3, left: 4, right: 4),
                  child: Text(
                    Formatters.time(message.createdAt!),
                    style: const TextStyle(
                      fontSize: 10.5,
                      color: AppColors.textTertiary,
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

/// Sub-tab B — one-off paid consultations.
class ConsultationListView extends ConsumerWidget {
  const ConsultationListView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppLocalizations l10n = context.l10n;
    final AsyncValue<Paged<Consultation>> consultations =
        ref.watch(myConsultationsProvider);

    return Scaffold(
      body: AsyncView<Paged<Consultation>>(
        value: consultations,
        onRetry: () => ref.invalidate(myConsultationsProvider),
        builder: (Paged<Consultation> page) {
          if (page.items.isEmpty) {
            return EmptyView(
              icon: Icons.forum_outlined,
              title: l10n.t('patient.no_consultations'),
            );
          }
          return RefreshIndicator(
            onRefresh: () async => ref.invalidate(myConsultationsProvider),
            child: ListView.separated(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.lg,
                AppSpacing.lg,
                AppSpacing.lg,
                96,
              ),
              itemCount: page.items.length,
              separatorBuilder: (_, __) => const SizedBox(height: AppSpacing.md),
              itemBuilder: (BuildContext context, int index) =>
                  ConsultationCard(consultation: page.items[index]),
            ),
          );
        },
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () async {
          final bool? created = await Navigator.of(context).push<bool>(
            MaterialPageRoute<bool>(builder: (_) => const NewConsultationFlow()),
          );
          if (created ?? false) ref.invalidate(myConsultationsProvider);
        },
        icon: const Icon(Icons.add_rounded),
        label: Text(l10n.t('patient.new_consultation')),
      ),
    );
  }
}
