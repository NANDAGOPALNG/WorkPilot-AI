export default function Card({ title, children, className = '', ...props }) {
  return (
    <section className={`card ${className}`} {...props}>
      {title && <h2 className="card-title">{title}</h2>}
      {children}
    </section>
  )
}
