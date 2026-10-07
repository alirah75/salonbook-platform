"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import {
  can,
  type CatalogService,
  type Line,
  type LineOffer,
} from "@/lib/dashboard";
import { money, number, type Page } from "@/lib/booking";
import { useResource, Pager } from "../booking/resource";
import { Field } from "../ui";
import {
  ActionForm,
  Check,
  Empty,
  Panel,
  ResourceState,
  Select,
  numeric,
  useWorkspace,
  useWrite,
  value,
} from "./shared";

export function CatalogPanel() {
  const { workspace, reload } = useWorkspace();
  const write = useWrite();
  const lines = workspace.lines.filter((l) =>
    can(workspace, "catalog.manage", l.id),
  );
  const [chosen, setChosen] = useState("");
  const [revision, setRevision] = useState(0);
  const line = lines.some((l) => l.id === chosen)
    ? chosen
    : (lines[0]?.id ?? "");
  return (
    <>
      <div className="work-heading">
        <span className="eyebrow">ویترین سالن</span>
        <h1>لاین‌ها و خدمات</h1>
        <p>قیمت و زمان هر خدمت را برای لاین مربوط به آن تنظیم کنید.</p>
      </div>
      {can(workspace, "catalog.manage") && (
        <details className="work-details work-panel">
          <summary>ساخت لاین جدید</summary>
          <ActionForm
            label="ساخت لاین"
            reset
            submit={async (d) => {
              const result = await write<Line>("/lines", {
                name: value(d, "name"),
                slug: value(d, "slug"),
              });
              setChosen(result.id);
              reload();
            }}
          >
            <Field name="name" label="نام لاین" required maxLength={120} />
            <Field
              name="slug"
              label="شناسهٔ لاتین لاین"
              dir="ltr"
              pattern="[a-z0-9]+(-[a-z0-9]+)*"
              required
              maxLength={100}
              hint="مثلاً hair-studio"
            />
          </ActionForm>
        </details>
      )}
      <Select
        label="انتخاب لاین"
        value={line}
        onChange={(e) => setChosen(e.target.value)}
      >
        {lines.map((l) => (
          <option value={l.id} key={l.id}>
            {l.name}
          </option>
        ))}
      </Select>
      {line ? (
        <LineCatalog key={line} line={line} revision={revision} />
      ) : (
        <Empty>ابتدا یک لاین بسازید.</Empty>
      )}
      {can(workspace, "catalog.manage") && (
        <ServiceDefinitions changed={() => setRevision((r) => r + 1)} />
      )}
    </>
  );
}
function LineCatalog({ line, revision }: { line: string; revision: number }) {
  const { workspace, reload } = useWorkspace();
  const write = useWrite();
  const [offset, setOffset] = useState(0);
  const [serviceOffset, setServiceOffset] = useState(0);
  const offers = useResource<Page<LineOffer>>(
    `/lines/${line}/services?limit=24&offset=${offset}`,
    0,
    api,
    revision,
  );
  const definitions = useResource<Page<CatalogService>>(
    `/services?limit=24&offset=${serviceOffset}`,
    0,
    api,
    revision,
  );
  const allLines = useResource<Line>(`/lines/${line}`);
  const current = allLines.data;
  return (
    <>
      <Panel title="خدمات این لاین">
        <ResourceState resource={offers} />
        {current && (
          <details className="work-details">
            <summary>ویرایش نام و وضعیت لاین</summary>
            <ActionForm
              submit={async (d) => {
                await write(
                  `/lines/${line}`,
                  { name: value(d, "name"), is_active: d.has("active") },
                  "PATCH",
                );
                allLines.reload();
                reload();
              }}
            >
              <Field
                name="name"
                label="نام لاین"
                defaultValue={current.name}
                maxLength={120}
                required
              />
              <Check
                label="لاین فعال است"
                name="active"
                defaultChecked={current.is_active}
              />
            </ActionForm>
          </details>
        )}
        {offers.data && !offers.error && (
          <>
            <div className="work-cards">
              {offers.data.items.map((o) => (
                <article
                  className="work-item"
                  key={`${o.id}:${JSON.stringify(o)}`}
                >
                  <div className="work-row">
                    <h3>{o.service_name}</h3>
                    <span className="work-badge">
                      {o.effective_active ? "فعال" : "غیرفعال"}
                    </span>
                  </div>
                  <p>
                    {money(o.price_amount)} · {number(o.duration_minutes)} دقیقه
                  </p>
                  <details className="work-details">
                    <summary>ویرایش این خدمت</summary>
                    <OfferForm line={line} offer={o} done={offers.reload} />
                  </details>
                </article>
              ))}
            </div>
            {!offers.data.items.length && (
              <Empty>خدمتی به این لاین اضافه نشده است.</Empty>
            )}
            <Pager
              offset={offset}
              hasMore={offers.data.has_more}
              change={setOffset}
            />
          </>
        )}
        <details className="work-details">
          <summary>افزودن خدمت به لاین</summary>
          <ResourceState resource={definitions} />
          {definitions.data && (
            <>
              <OfferForm
                line={line}
                services={definitions.data.items}
                done={offers.reload}
                key={serviceOffset}
              />
              <Pager
                offset={serviceOffset}
                hasMore={definitions.data.has_more}
                change={setServiceOffset}
              />
            </>
          )}
        </details>
        <p className="muted">
          قیمت تازه برای رزروهای جدید است؛ مبلغ نوبت‌های قبلی حفظ می‌شود.
        </p>
      </Panel>
      {!can(workspace, "catalog.manage") && (
        <p className="muted">
          تعریف خدمت جدید در اختیار مدیر سالن است. قیمت و زمان خدمات این لاین را
          اینجا تنظیم کنید.
        </p>
      )}
    </>
  );
}
function OfferForm({
  line,
  offer,
  services,
  done,
}: {
  line: string;
  offer?: LineOffer;
  services?: CatalogService[];
  done: () => void;
}) {
  const write = useWrite();
  return (
    <ActionForm
      label={offer ? "ذخیرهٔ خدمت" : "افزودن خدمت"}
      disabled={!offer && !services?.length}
      submit={async (d) => {
        await write(
          `/lines/${line}/services/${offer?.service_id ?? value(d, "service")}`,
          {
            price_amount: numeric(d, "price"),
            duration_minutes: numeric(d, "duration"),
            buffer_before_minutes: numeric(d, "before"),
            buffer_after_minutes: numeric(d, "after"),
            is_free: d.has("free"),
            is_active: d.has("active"),
          },
          "PUT",
        );
        done();
      }}
    >
      {!offer && (
        <Select name="service" label="خدمت" required>
          {services?.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
              {!s.is_active ? " (غیرفعال)" : ""}
            </option>
          ))}
        </Select>
      )}
      <div className="work-grid">
        <Field
          name="price"
          label="قیمت (ریال)"
          type="number"
          required
          min={0}
          max={Number.MAX_SAFE_INTEGER}
          step={1}
          defaultValue={offer?.price_amount ?? 0}
        />
        <Field
          name="duration"
          label="مدت خدمت (دقیقه)"
          type="number"
          required
          min={1}
          max={1440}
          defaultValue={offer?.duration_minutes ?? 30}
        />
        <Field
          name="before"
          label="آماده‌سازی پیش از خدمت (دقیقه)"
          type="number"
          required
          min={0}
          max={240}
          defaultValue={offer?.buffer_before_minutes ?? 0}
        />
        <Field
          name="after"
          label="فاصلهٔ پس از خدمت (دقیقه)"
          type="number"
          required
          min={0}
          max={240}
          defaultValue={offer?.buffer_after_minutes ?? 0}
        />
      </div>
      <Check
        label="این خدمت رایگان است (قیمت صفر)"
        name="free"
        defaultChecked={offer?.is_free ?? false}
      />
      <Check
        label="ارائهٔ خدمت فعال است"
        name="active"
        defaultChecked={offer?.is_active ?? true}
      />
    </ActionForm>
  );
}
function ServiceDefinitions({ changed }: { changed: () => void }) {
  const write = useWrite();
  const [offset, setOffset] = useState(0);
  const services = useResource<Page<CatalogService>>(
    `/services?limit=24&offset=${offset}`,
  );
  return (
    <Panel title="تعریف خدمات سالن">
      <details className="work-details">
        <summary>تعریف خدمت جدید</summary>
        <ActionForm
          label="ساخت خدمت"
          reset
          submit={async (d) => {
            await write("/services", {
              name: value(d, "name"),
              code: value(d, "code"),
              description: value(d, "description") || null,
            });
            services.reload();
            changed();
          }}
        >
          <Field label="نام خدمت" name="name" required maxLength={160} />
          <Field
            label="کد لاتین خدمت"
            name="code"
            required
            maxLength={80}
            pattern="[a-z0-9]+([_-][a-z0-9]+)*"
            dir="ltr"
          />
          <Field label="توضیح خدمت" name="description" maxLength={4000} />
        </ActionForm>
      </details>
      <ResourceState resource={services} />
      {services.data && !services.error && (
        <>
          <div className="work-stack">
            {services.data.items.map((s) => (
              <details
                className="work-details"
                key={`${s.id}:${JSON.stringify(s)}`}
              >
                <summary>
                  {s.name} · {s.is_active ? "فعال" : "غیرفعال"}
                </summary>
                <ActionForm
                  submit={async (d) => {
                    await write(
                      `/services/${s.id}`,
                      {
                        name: value(d, "name"),
                        description: value(d, "description") || null,
                        is_active: d.has("active"),
                      },
                      "PATCH",
                    );
                    services.reload();
                    changed();
                  }}
                >
                  <Field
                    label="نام خدمت"
                    name="name"
                    required
                    maxLength={160}
                    defaultValue={s.name}
                  />
                  <Field
                    label="توضیح خدمت"
                    name="description"
                    maxLength={4000}
                    defaultValue={s.description ?? ""}
                  />
                  <Check
                    label="خدمت در سالن فعال است"
                    name="active"
                    defaultChecked={s.is_active}
                  />
                </ActionForm>
              </details>
            ))}
          </div>
          <Pager
            offset={offset}
            hasMore={services.data.has_more}
            change={setOffset}
          />
        </>
      )}
    </Panel>
  );
}
