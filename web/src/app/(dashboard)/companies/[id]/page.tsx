import { notFound } from "next/navigation";
import Link from "next/link";
import { getCompanyById, getCampaignsByCompany, getContactsByCompany } from "@/lib/queries";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BodyContent } from "@/components/body-content";

function scoreColor(score: number | null): string {
  if (score === null || score === undefined) return "";
  if (score >= 7) return "text-primary font-semibold";
  if (score >= 4) return "";
  return "text-destructive font-semibold";
}

export default async function CompanyDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [company, campaigns, contacts] = await Promise.all([
    getCompanyById(id),
    getCampaignsByCompany(id),
    getContactsByCompany(id),
  ]);

  if (!company) notFound();

  const props = [
    {
      label: "Website",
      value: company.website ? (
        <a
          href={company.website}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary hover:underline"
        >
          {company.website.replace(/^https?:\/\//, "")}
        </a>
      ) : (
        "--"
      ),
    },
    { label: "Industry", value: company.industry || "--" },
    { label: "Location", value: company.location || "--" },
    { label: "Size", value: company.size || "--" },
    {
      label: "DPP Fit Score",
      value: (
        <span className={scoreColor(company.dpp_fit_score)}>
          {company.dpp_fit_score !== null && company.dpp_fit_score !== undefined
            ? String(company.dpp_fit_score)
            : "--"}
        </span>
      ),
    },
    { label: "Status", value: <Badge variant="outline">{company.status}</Badge> },
  ];

  return (
    <div className="space-y-6">
      {/* Back link */}
      <Link
        prefetch
        href="/companies"
        className="text-sm text-muted-foreground hover:text-foreground"
      >
        &larr; Companies
      </Link>

      {/* Heading */}
      <h1 className="text-2xl font-semibold text-foreground">{company.name}</h1>

      {/* Properties grid */}
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

      {/* Campaigns */}
      {campaigns.length > 0 && (
        <div className="flex flex-wrap gap-2">
          <span className="text-sm text-muted-foreground mr-1">Campaigns:</span>
          {campaigns.map((camp: Record<string, unknown>) => (
            <Badge key={camp.id as string} variant="default">
              {camp.name as string}
            </Badge>
          ))}
        </div>
      )}

      {/* Enrichment Report */}
      <Card>
        <CardHeader>
          <CardTitle>Enrichment Report</CardTitle>
        </CardHeader>
        <CardContent>
          <BodyContent text={company.body} />
        </CardContent>
      </Card>

      {/* Contacts at this company */}
      {contacts.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Contacts</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {contacts.map((ct: Record<string, unknown>) => (
                <li key={ct.id as string}>
                  <Link
                    prefetch
                    href={`/contacts/${ct.id}`}
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
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
