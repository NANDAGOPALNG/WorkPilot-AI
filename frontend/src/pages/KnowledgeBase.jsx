import DocumentList from '../components/knowledge/DocumentList'
import DocumentUpload from '../components/knowledge/DocumentUpload'
import { useDocuments } from '../hooks/useDocuments'

export default function KnowledgeBase() {
  const { documents, loading, error, refresh } = useDocuments()
  return (
    <div className="kb">
      <div className="kb-intro">
        <h2>Knowledge Base</h2>
        <p>
          The documents you upload here power WorkPilot's knowledge and answers. The assistant searches them to
          respond to questions about your company, so keep the library current.
        </p>
      </div>
      <DocumentUpload onUploadFinished={refresh} />
      <DocumentList documents={documents} loading={loading} error={error} onRefresh={refresh} />
    </div>
  )
}
