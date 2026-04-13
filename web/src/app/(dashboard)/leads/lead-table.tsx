import { Badge } from "@/components/ui/badge";
import {
  TableCell,
  TableRow,
} from "@/components/ui/table";
import { OutreachSelect } from "./outreach-select";

export interface LeadRow {
  id: string;
  name: string;
  job_title: string | null;
  company_name: string | null;
  email: string | null;
  linkedin_url: string | null;
  company_fit_score: number | null;
  relevance_score: number | null;
  outreach_status: string;
  email_subject: string | null;
  campaign_id: string;
  campaign_name?: string | null;
  score_reasoning: string | null;
  context: string | null;
  personalized_context: string | null;
  company_url: string | null;
  email_body: string | null;
}

function scoreVariant(score: number | null): "success" | "warning" | "default" {
  if (score == null) return "default";
  if (score >= 8) return "success";
  if (score >= 7) return "warning";
  return "default";
}

function displayUrl(url: string): string {
  return url.replace(/^https?:\/\//, "").replace(/\/$/, "");
}

export function LeadTableRow({ lead }: { lead: LeadRow }) {
  return (
    <TableRow key={lead.id}>
      <TableCell className="font-medium">
        {lead.company_name ?? "--"}
      </TableCell>
      <TableCell>
        {lead.company_url ? (
          <a
            href={lead.company_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary hover:underline underline-offset-4 text-xs"
          >
            {displayUrl(lead.company_url)}
          </a>
        ) : (
          <span className="text-muted-foreground">--</span>
        )}
      </TableCell>
      <TableCell>{lead.name}</TableCell>
      <TableCell className="text-muted-foreground">
        {lead.job_title ?? "--"}
      </TableCell>
      <TableCell className="font-mono text-xs">
        {lead.email ? (
          <a
            href={`mailto:${lead.email}`}
            className="text-primary hover:underline underline-offset-4"
          >
            {lead.email}
          </a>
        ) : (
          <span className="text-muted-foreground">--</span>
        )}
      </TableCell>
      <TableCell>
        {lead.linkedin_url ? (
          <a
            href={lead.linkedin_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary hover:underline underline-offset-4"
          >
            Profile
          </a>
        ) : (
          <span className="text-muted-foreground">--</span>
        )}
      </TableCell>
      <TableCell className="text-right">
        <Badge variant={scoreVariant(lead.company_fit_score)} dot={false}>
          {lead.company_fit_score ?? "--"}
        </Badge>
      </TableCell>
      <TableCell className="text-right">
        <Badge variant={scoreVariant(lead.relevance_score)} dot={false}>
          {lead.relevance_score ?? "--"}
        </Badge>
      </TableCell>
      <TableCell className="text-muted-foreground text-xs">
        {lead.email_subject ?? "--"}
      </TableCell>
      <TableCell className="max-w-[200px]">
        <span className="text-xs text-muted-foreground line-clamp-2">
          {lead.email_body ?? "--"}
        </span>
      </TableCell>
      <TableCell>
        <OutreachSelect
          leadId={lead.id}
          current={lead.outreach_status}
        />
      </TableCell>
      <TableCell className="max-w-[180px]">
        <span className="text-xs text-muted-foreground line-clamp-2">
          {lead.score_reasoning ?? "--"}
        </span>
      </TableCell>
      <TableCell className="max-w-[180px]">
        <span className="text-xs text-muted-foreground line-clamp-2">
          {lead.context ?? "--"}
        </span>
      </TableCell>
      <TableCell className="max-w-[180px]">
        <span className="text-xs text-muted-foreground line-clamp-2">
          {lead.personalized_context ?? "--"}
        </span>
      </TableCell>
    </TableRow>
  );
}
