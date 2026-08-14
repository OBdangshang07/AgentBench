import { Braces } from "lucide-react";

interface JsonSchema {
  type?: string | string[];
  title?: string;
  description?: string;
  enum?: unknown[];
  default?: unknown;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
}

function schemaType(schema: JsonSchema) {
  return Array.isArray(schema.type) ? schema.type.find((item) => item !== "null") ?? "string" : schema.type ?? "string";
}

function updatePath(source: Record<string, unknown>, path: string[], next: unknown) {
  const output = structuredClone(source);
  let current: Record<string, unknown> = output;
  path.slice(0, -1).forEach((part) => {
    const child = current[part];
    current[part] = child && typeof child === "object" && !Array.isArray(child) ? { ...child as Record<string, unknown> } : {};
    current = current[part] as Record<string, unknown>;
  });
  current[path.at(-1)!] = next;
  return output;
}

function SchemaField({
  name,
  schema,
  value,
  required,
  path,
  root,
  disabled,
  onChange,
}: {
  name: string;
  schema: JsonSchema;
  value: unknown;
  required: boolean;
  path: string[];
  root: Record<string, unknown>;
  disabled: boolean;
  onChange: (value: Record<string, unknown>) => void;
}) {
  const type = schemaType(schema);
  const label = schema.title || name;
  const set = (next: unknown) => onChange(updatePath(root, path, next));
  if (type === "object" && schema.properties) {
    const objectValue = value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
    return <fieldset className="v5-schema-object"><legend>{label}{required && <b>*</b>}</legend>{schema.description && <p>{schema.description}</p>}<div>{Object.entries(schema.properties).map(([childName, child]) => <SchemaField key={childName} name={childName} schema={child} value={objectValue[childName]} required={schema.required?.includes(childName) ?? false} path={[...path, childName]} root={root} disabled={disabled} onChange={onChange} />)}</div></fieldset>;
  }
  if (schema.enum?.length) {
    return <label className="v5-schema-field"><span>{label}{required && <b>*</b>}</span><select value={String(value ?? schema.default ?? "")} disabled={disabled} onChange={(event) => set(event.target.value)}><option value="">请选择</option>{schema.enum.map((item) => <option key={String(item)} value={String(item)}>{String(item)}</option>)}</select>{schema.description && <small>{schema.description}</small>}</label>;
  }
  if (type === "boolean") {
    return <label className="v5-schema-field boolean"><input type="checkbox" checked={Boolean(value ?? schema.default)} disabled={disabled} onChange={(event) => set(event.target.checked)} /><i /><span>{label}{required && <b>*</b>}<small>{schema.description}</small></span></label>;
  }
  if (type === "number" || type === "integer") {
    return <label className="v5-schema-field"><span>{label}{required && <b>*</b>}</span><input type="number" step={type === "integer" ? 1 : "any"} value={value === undefined ? String(schema.default ?? "") : String(value)} disabled={disabled} onChange={(event) => set(event.target.value === "" ? null : Number(event.target.value))} />{schema.description && <small>{schema.description}</small>}</label>;
  }
  if (type === "array") {
    return <label className="v5-schema-field"><span>{label}{required && <b>*</b>}</span><textarea value={JSON.stringify(value ?? schema.default ?? [], null, 2)} disabled={disabled} onChange={(event) => { try { set(JSON.parse(event.target.value)); } catch { /* Keep the last valid array while typing. */ } }} spellCheck={false} />{schema.description && <small>{schema.description}</small>}</label>;
  }
  return <label className="v5-schema-field"><span>{label}{required && <b>*</b>}</span>{schema.description && schema.description.length > 100 ? <textarea value={String(value ?? schema.default ?? "")} disabled={disabled} onChange={(event) => set(event.target.value)} /> : <input value={String(value ?? schema.default ?? "")} disabled={disabled} onChange={(event) => set(event.target.value)} />}{schema.description && <small>{schema.description}</small>}</label>;
}

export default function JsonSchemaForm({ schema, value, disabled = false, onChange }: { schema?: Record<string, unknown>; value: Record<string, unknown>; disabled?: boolean; onChange: (value: Record<string, unknown>) => void }) {
  const typed = schema as JsonSchema | undefined;
  if (!typed?.properties || !Object.keys(typed.properties).length) return <div className="v5-schema-empty"><Braces size={16} /><span>该工具没有声明参数 Schema，可使用高级 JSON 编辑器。</span></div>;
  return <div className="v5-schema-form">{Object.entries(typed.properties).map(([name, property]) => <SchemaField key={name} name={name} schema={property} value={value[name]} required={typed.required?.includes(name) ?? false} path={[name]} root={value} disabled={disabled} onChange={onChange} />)}</div>;
}
