import { BookOpen, FileText, Mic, Ticket } from 'lucide-react'

export const NAV_ITEMS = [
  { to: '/assistant', label: 'Assistant', icon: Mic, title: 'Voice Assistant', subtitle: 'Talk to WorkPilot in real time.' },
  { to: '/knowledge', label: 'Knowledge Base', icon: BookOpen, title: 'Knowledge Base', subtitle: 'Company documents the assistant can use.' },
  { to: '/tickets', label: 'Tickets', icon: Ticket, title: 'Tickets', subtitle: 'Support tickets.' },
  { to: '/documentation', label: 'Documentation', icon: FileText, title: 'Documentation', subtitle: 'Generated reports and summaries.' },
]
