import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BodyContent } from "@/components/body-content";

interface ContactDetailProps {
  contact: Record<string, unknown>;
  backUrl: string;
  campaignId?: string;
}

export function ContactDetail({ contact, backUrl, campaignId }: ContactDetailProps) {
  const companyHref = contact.company_id
    ? campaignId
      ? `/campaigns/${campaignId}/companies/${contact.company_id}`
      : `/companies/${contact.company_id}`
    : null;

  const props = [
    {
      label: "Email",
      value: (contact.email as string) || "--",
    },
    {
      label: "LinkedIn",
      value: contact.linkedin_url ? (
        <a
          href={contact.linkedin_url as string}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary hover:underline"
        >
          Profile
        </a>
      ) : (
        "--"
      ),
    },
    {
      label: "Company",
      value: companyHref ? (
        <Link
          prefetch
          href={companyHref}
          className="text-primary hover:underline"
        >
          {(contact.company_name as string) || "--"}
        </Link>
      ) : (
        "--"
      ),
    },
    {
      label: "Status",
      value: <Badge variant="outline">{contact.status as string}</Badge>,
    },
    {
      label: "Email Verified",
      value: contact.email_verified ? "Yes" : "No",
    },
  ];

  return (
    <div className="space-y-6">
      <Link
        prefetch
        href={backUrl}
        className="text-sm text-muted-foreground hover:text-foreground"
      >
        &larr; Contacts
      </Link>

      <div>
        <h1 className="text-2xl font-semibold text-foreground">
          {String(contact.name)}
        </h1>
        {contact.job_title ? (
          <p className="text-sm text-muted-foreground mt-1">
            {String(contact.job_title)}
          </p>
        ) : null}
      </div>

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

      {contact.context ? (
        <Card>
          <CardHeader>
            <CardTitle>Context</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">{contact.context as string}</p>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Person Research</CardTitle>
        </CardHeader>
        <CardContent>
          <BodyContent text={contact.body as string} />
        </CardContent>
      </Card>
    </div>
  );
}
