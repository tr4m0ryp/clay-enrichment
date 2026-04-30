import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import {
  TableCell,
  TableRow,
} from "@/components/ui/table";
import { ExpandableCell } from "@/components/ui/expandable-cell";

export interface LeadRow {
  id: string;
  name: string;
  job_title: string | null;
  company_name: string | null;
  email: string | null;
  email_verified: boolean;
  linkedin_url: string | null;
  company_fit_score: number | null;
  relevance_score: number | null;
  email_subject: string | null;
  campaign_id: string;
  campaign_name?: string | null;
  score_reasoning: string | null;
  context: string | null;
  personalized_context: string | null;
  company_url: string | null;
  company_id: string | null;
  contact_id: string | null;
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
        {lead.company_id && lead.company_name ? (
          <Link
            prefetch
            href={`/companies/${lead.company_id}?from=leads`}
            className="text-primary hover:underline underline-offset-4"
          >
            {lead.company_name}
          </Link>
        ) : (
          lead.company_name ?? "--"
        )}
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
      <TableCell>
        {lead.contact_id ? (
          <Link
            prefetch
            href={`/contacts/${lead.contact_id}?from=leads`}
            className="text-primary hover:underline underline-offset-4"
          >
            {lead.name}
          </Link>
        ) : (
          lead.name
        )}
      </TableCell>
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
        {lead.email ? (
          <Badge
            variant={lead.email_verified ? "success" : "outline"}
            dot={false}
          >
            {lead.email_verified ? "Verified" : "Unverified"}
          </Badge>
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
      <TableCell className="max-w-[200px]">
        <ExpandableCell label="Email Subject" content={lead.email_subject} />
      </TableCell>
      <TableCell className="max-w-[200px]">
        <ExpandableCell label="Email Content" content={lead.email_body} />
      </TableCell>
      <TableCell className="max-w-[180px]">
        <ExpandableCell label="Score Reasoning" content={lead.score_reasoning} />
      </TableCell>
      <TableCell className="max-w-[180px]">
        <ExpandableCell label="Context" content={lead.context} />
      </TableCell>
      <TableCell className="max-w-[180px]">
        <ExpandableCell
          label="Personalized Context"
          content={lead.personalized_context}
        />
      </TableCell>
    </TableRow>
  );
}
