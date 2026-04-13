import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BodyContent } from "@/components/body-content";

function scoreColor(score: number | null): string {
  if (score === null || score === undefined) return "";
  if (score >= 7) return "text-primary font-semibold";
  if (score >= 4) return "";
  return "text-destructive font-semibold";
}

interface CompanyDetailProps {
  company: Record<string, unknown>;
  campaigns: Record<string, unknown>[];
  contacts: Record<string, unknown>[];
  backUrl: string;
  campaignId?: string;
}

export function CompanyDetail({
  company,
  campaigns,
  contacts,
  backUrl,
  campaignId,
}: CompanyDetailProps) {
  const props = [
    {
      label: "Website",
      value: company.website ? (
        <a
          href={company.website as string}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary hover:underline"
        >
          {(company.website as string).replace(/^https?:\/\//, "")}
        </a>
      ) : (
        "--"
      ),
    },
    { label: "Industry", value: (company.industry as string) || "--" },
    { label: "Location", value: (company.location as string) || "--" },
    { label: "Size", value: (company.size as string) || "--" },
    {
      label: "DPP Fit Score",
      value: (
        <span className={scoreColor(company.dpp_fit_score as number | null)}>
          {company.dpp_fit_score !== null && company.dpp_fit_score !== undefined
            ? String(company.dpp_fit_score)
            : "--"}
        </span>
      ),
    },
    { label: "Status", value: <Badge variant="outline">{company.status as string}</Badge> },
  ];

  return (
    <div className="space-y-6">
      <Link
        prefetch
        href={backUrl}
        className="text-sm text-muted-foreground hover:text-foreground"
      >
        &larr; Companies
      </Link>

      <h1 className="text-2xl font-semibold text-foreground">{company.name as string}</h1>

      <Card>
        <CardHeader>
          <CardTitle>Properties</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-3">
            {props.map((p) => (
              <div key={p.label}>
                <dt className="text-xs text-muted-foreground">{p.label}</dt>
                <dd className="text-sm mt-0.5">{p.value}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>

      {campaigns.length > 0 && (
        <div className="flex flex-wrap gap-2">
          <span className="text-sm text-muted-foreground mr-1">Campaigns:</span>
          {campaigns.map((camp) => (
            <Badge key={camp.id as string} variant="default">
              {camp.name as string}
            </Badge>
          ))}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Enrichment Report</CardTitle>
        </CardHeader>
        <CardContent>
          <BodyContent text={company.body as string} />
        </CardContent>
      </Card>

      {contacts.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Contacts</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {contacts.map((ct) => {
                const contactHref = campaignId
                  ? `/campaigns/${campaignId}/contacts/${ct.id}`
                  : `/contacts/${ct.id}`;
                return (
                  <li key={ct.id as string}>
                    <Link
                      prefetch
                      href={contactHref}
                      className="text-sm text-primary hover:underline"
                    >
                      {ct.name as string}
                    </Link>
                    {ct.job_title ? (
                      <span className="text-sm text-muted-foreground ml-2">
                        -- {String(ct.job_title)}
                      </span>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
