"use client";
import Link from "next/link";
import { useState } from "react";
import { can, type LineOffer } from "@/lib/dashboard";
import type { Page, Employee } from "@/lib/booking";
import { useResource, Pager } from "../booking/resource";
import {
  ActionForm,
  Check,
  Empty,
  Panel,
  ResourceState,
  Select,
  useWorkspace,
  useWrite,
  value,
} from "./shared";

type Member = {
  id: string;
  employee_id: string;
  public_name: string;
  is_active: boolean;
  effective_active: boolean;
};
type Skill = {
  id: string;
  service_id: string;
  service_name: string;
  is_active: boolean;
  effective_active: boolean;
};
export function TeamPanel() {
  const { workspace } = useWorkspace();
  const lines = workspace.lines.filter((l) =>
    can(workspace, "staff.assign", l.id),
  );
  const [chosen, setChosen] = useState("");
  const line = lines.some((l) => l.id === chosen)
    ? chosen
    : (lines[0]?.id ?? "");
  return (
    <>
      <div className="work-heading">
        <span className="eyebrow">همکاران شما</span>
        <h1>تیم و مهارت‌ها</h1>
        <p>کارکنان هر لاین و خدماتی که ارائه می‌کنند را مشخص کنید.</p>
      </div>
      {can(workspace, "users.manage") && (
        <Link className="text-link" href="/dashboard/users">
          ساخت حساب کارمند جدید ←
        </Link>
      )}
      <Select
        label="لاین تیم"
        value={line}
        onChange={(e) => setChosen(e.target.value)}
      >
        {lines.map((l) => (
          <option key={l.id} value={l.id}>
            {l.name}
          </option>
        ))}
      </Select>
      {line ? (
        <LineTeam key={line} line={line} />
      ) : (
        <Empty>برای تخصیص کارکنان، دسترسی به یک لاین لازم است.</Empty>
      )}
    </>
  );
}
function LineTeam({ line }: { line: string }) {
  const write = useWrite();
  const [offset, setOffset] = useState(0);
  const [candidateOffset, setCandidateOffset] = useState(0);
  const members = useResource<Page<Member>>(
    `/lines/${line}/employees?limit=24&offset=${offset}`,
  );
  const candidates = useResource<Page<Employee>>(
    `/lines/${line}/employee-candidates?limit=24&offset=${candidateOffset}`,
  );
  return (
    <Panel title="کارکنان لاین">
      <ResourceState resource={members} />
      {members.data && !members.error && (
        <>
          <div className="work-stack">
            {members.data.items.map((member) => (
              <article
                className="work-item"
                key={`${member.id}:${member.is_active}`}
              >
                <div className="work-row">
                  <h3>{member.public_name}</h3>
                  <span className="work-badge">
                    {member.effective_active ? "فعال" : "غیرفعال"}
                  </span>
                </div>
                <details className="work-details">
                  <summary>مهارت‌ها و وضعیت همکاری</summary>
                  <ActionForm
                    label="ذخیرهٔ وضعیت همکاری"
                    submit={async (d) => {
                      await write(
                        `/lines/${line}/employees/${member.employee_id}`,
                        { is_active: d.has("active") },
                        "PUT",
                      );
                      members.reload();
                    }}
                  >
                    <Check
                      label="همکاری در این لاین فعال است"
                      name="active"
                      defaultChecked={member.is_active}
                    />
                  </ActionForm>
                  <Skills line={line} employee={member.employee_id} />
                </details>
              </article>
            ))}
          </div>
          {!members.data.items.length && <Empty />}
          <Pager
            offset={offset}
            hasMore={members.data.has_more}
            change={setOffset}
          />
        </>
      )}
      <details className="work-details">
        <summary>افزودن کارمند به این لاین</summary>
        <ResourceState resource={candidates} />
        {candidates.data && (
          <>
            <ActionForm
              label="افزودن به تیم"
              disabled={!candidates.data.items.length}
              submit={async (d) => {
                await write(
                  `/lines/${line}/employees/${value(d, "employee")}`,
                  { is_active: true },
                  "PUT",
                );
                members.reload();
                candidates.reload();
              }}
            >
              <Select name="employee" label="انتخاب کارمند" required>
                {candidates.data.items.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.public_name}
                  </option>
                ))}
              </Select>
            </ActionForm>
            <Pager
              offset={candidateOffset}
              hasMore={candidates.data.has_more}
              change={setCandidateOffset}
            />
          </>
        )}
      </details>
    </Panel>
  );
}
function Skills({ line, employee }: { line: string; employee: string }) {
  const write = useWrite();
  const [offset, setOffset] = useState(0);
  const [offerOffset, setOfferOffset] = useState(0);
  const path = `/lines/${line}/employees/${employee}/services`;
  const skills = useResource<Page<Skill>>(`${path}?limit=24&offset=${offset}`);
  const offers = useResource<Page<LineOffer>>(
    `/lines/${line}/services?limit=24&offset=${offerOffset}`,
  );
  return (
    <div className="work-subpanel">
      <h4>خدمات قابل ارائه</h4>
      <ResourceState resource={skills} />
      {skills.data && (
        <>
          <ul className="work-list">
            {skills.data.items.map((s) => (
              <li key={`${s.id}:${s.is_active}`}>
                <ActionForm
                  label="ذخیرهٔ مهارت"
                  submit={async (d) => {
                    await write(
                      `${path}/${s.service_id}`,
                      { is_active: d.has("active") },
                      "PUT",
                    );
                    skills.reload();
                  }}
                >
                  <Check
                    label={s.service_name}
                    name="active"
                    defaultChecked={s.is_active}
                  />
                </ActionForm>
              </li>
            ))}
          </ul>
          <Pager
            offset={offset}
            hasMore={skills.data.has_more}
            change={setOffset}
          />
        </>
      )}
      <ResourceState resource={offers} />
      {offers.data && (
        <>
          <ActionForm
            label="افزودن مهارت"
            disabled={!offers.data.items.length}
            submit={async (d) => {
              await write(
                `${path}/${value(d, "service")}`,
                { is_active: true },
                "PUT",
              );
              skills.reload();
            }}
          >
            <Select label="خدمت قابل ارائه" name="service" required>
              {offers.data.items.map((o) => (
                <option key={o.service_id} value={o.service_id}>
                  {o.service_name}
                </option>
              ))}
            </Select>
          </ActionForm>
          <Pager
            offset={offerOffset}
            hasMore={offers.data.has_more}
            change={setOfferOffset}
          />
        </>
      )}
    </div>
  );
}
